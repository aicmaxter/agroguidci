/**
 * /api/demande — proxy same-origin vers le moteur AGROGUIDCI (VPS).
 *
 * Pourquoi un proxy et pas une réécriture : la clé du moteur reste côté serveur
 * (variable d'environnement Vercel), jamais dans la page ni dans le dépôt.
 *
 * Variables d'environnement (projet Vercel « agroguidci-site ») :
 *   AGRO_ENGINE_URL  URL du moteur, ex. https://api.mon-domaine.tld
 *   AGRO_ENGINE_KEY  clé d'API du moteur (X-API-Key)
 * Sans AGRO_ENGINE_URL, on retombe sur le moteur hébergé actuel pour ne pas casser
 * le site pendant la bascule.
 *
 * Mode asynchrone imposé : une coordination dure 40 à 120 s, alors qu'une fonction
 * Vercel est coupée bien avant. Un POST sans `async: true` est donc relayé en mode
 * asynchrone ; la réponse 202 porte l'identifiant à suivre sur /api/missions/{id}
 * (même origine). Le mode synchrone n'est pas exposé par ce proxy.
 */

const DEFAUT = "https://agroguidci-saas.vercel.app";

function base() {
  return (process.env.AGRO_ENGINE_URL || DEFAUT).replace(/\/+$/, "");
}

/** Réécrit le champ `suivi` du moteur (relatif au moteur) vers la même origine. */
function memeOrigine(texte, statut) {
  if (statut !== 202) return texte;
  try {
    const corps = JSON.parse(texte);
    if (!corps || typeof corps.id !== "string") return texte;
    corps.suivi = "/api/missions/" + corps.id;
    return JSON.stringify(corps);
  } catch (e) {
    return texte;
  }
}

async function relayer(req, res, methode, charge) {
  const url = base() + "/api/demande";
  const entetes = { Accept: "application/json" };
  const cle = process.env.AGRO_ENGINE_KEY || "";
  if (cle) entetes["X-API-Key"] = cle;
  if (methode === "POST") entetes["Content-Type"] = "application/json";

  const ctrl = new AbortController();
  // En mode asynchrone le moteur rend un 202 en quelques millisecondes : ce délai
  // couvre une mise en route lente du VPS, pas une coordination complète.
  const minuteur = setTimeout(() => ctrl.abort(), 25000);   // le moteur répond 202 tout de suite
  try {
    const r = await fetch(url, {
      method: methode,
      headers: entetes,
      body: methode === "POST" ? JSON.stringify(charge || {}) : undefined,
      signal: ctrl.signal,
    });
    let texte = await r.text();
    if (methode === "POST") texte = memeOrigine(texte, r.status);
    res.statusCode = r.status;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    return res.end(texte);
  } catch (e) {
    const message = e && e.name === "AbortError"
      ? "le moteur n'a pas répondu dans le délai imparti"
      : "moteur injoignable";
    res.statusCode = 502;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    return res.end(JSON.stringify({ erreur: message }));
  } finally {
    clearTimeout(minuteur);
  }
}

module.exports = async function handler(req, res) {
  if (req.method === "OPTIONS") {
    res.setHeader("Allow", "GET, POST, OPTIONS");
    return res.status(204).end();
  }
  if (req.method === "POST") {
    const corps = req.body;
    const texte = corps && typeof corps === "object" ? corps.texte : "";
    if (typeof texte !== "string" || texte.trim().length < 5) {
      res.statusCode = 422;
      res.setHeader("Content-Type", "application/json; charset=utf-8");
      return res.end(JSON.stringify({ erreur: "texte trop court (5 caractères minimum)" }));
    }
    if (texte.length > 4000) {
      res.statusCode = 422;
      res.setHeader("Content-Type", "application/json; charset=utf-8");
      return res.end(JSON.stringify({ erreur: "texte trop long (4000 caractères maximum)" }));
    }
    // Une coordination dépasse la durée maximale d'une fonction Vercel : on impose
    // le mode asynchrone, même si le client ne l'a pas demandé.
    const charge = Object.assign({}, corps, { async: true });
    return relayer(req, res, "POST", charge);
  }
  if (req.method === "GET") return relayer(req, res, "GET");
  res.setHeader("Allow", "GET, POST, OPTIONS");
  res.statusCode = 405;
  return res.end(JSON.stringify({ erreur: "méthode non autorisée" }));
};

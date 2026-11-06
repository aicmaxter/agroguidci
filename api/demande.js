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

const { baseMoteur, texteBorne, lireCookie, ecrireCookie, appeler } = require("./_lib/engine");

function base() {
  return baseMoteur();
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
  const racine = base();
  if (!racine) {
    res.statusCode = 503;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    return res.end(JSON.stringify({ erreur: "Le service de réponse n'est pas configuré sur cet environnement." }));
  }
  const url = racine + "/api/demande";
  const entetes = { Accept: "application/json" };
  const cle = process.env.AGRO_ENGINE_KEY || "";
  if (cle) entetes["X-API-Key"] = cle;
  if (methode === "POST") entetes["Content-Type"] = "application/json";
  // IP du visiteur : Vercel la pose, le moteur s'en sert pour le quota quotidien.
  // Sans elle, tous les visiteurs partageraient l'IP de Vercel et le quota tomberait
  // sur le premier venu.
  const xff = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim();
  const ipVisiteur = /^[0-9a-fA-F:.]{3,45}$/.test(xff) ? xff : "";
  if (ipVisiteur) entetes["X-Client-IP"] = ipVisiteur;
  // Le moteur exige une session anonyme et débite un crédit par mission aboutie.
  // Le jeton reste dans un cookie HttpOnly : le navigateur ne voit jamais la clé.
  let jeton = lireCookie(req);

  // Deux tentatives au plus : la première avec le cookie courant, la seconde avec une
  // session neuve si le moteur répond 401 (cookie absent ou expiré). La session est
  // ouverte côté serveur et posée en cookie HttpOnly : le navigateur ne voit rien.
  let texte = "";
  let statut = 502;
  for (let essai = 0; essai < 2; essai++) {
    if (!jeton) {
      const session = await appeler("/api/sessions", { method: "POST", timeout: 10000 });
      if (session.status === 200 && session.donnees && session.donnees.session_token) {
        jeton = session.donnees.session_token;
        ecrireCookie(res, jeton);
      } else {
        res.statusCode = 502;
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        return res.end(JSON.stringify({ erreur: "session indisponible : réessayez dans un instant" }));
      }
    }
    const entetesAppel = Object.assign({}, entetes, { "X-Session-Token": jeton });
    const ctrl = new AbortController();
    // En mode asynchrone le moteur rend un 202 en quelques millisecondes : ce délai
    // couvre une mise en route lente du VPS, pas une coordination complète.
    const minuteur = setTimeout(() => ctrl.abort(), 25000);
    try {
      const r = await fetch(url, {
        method: methode,
        headers: entetesAppel,
        body: methode === "POST" ? JSON.stringify(charge || {}) : undefined,
        signal: ctrl.signal,
        redirect: "error",            // la clé ne suit pas une redirection
      });
      texte = await texteBorne(r);
      statut = r.status;
    } catch (e) {
      const expire = e && e.name === "AbortError";
      res.statusCode = expire ? 504 : 502;
      res.setHeader("Content-Type", "application/json; charset=utf-8");
      return res.end(JSON.stringify({
        erreur: expire ? "le moteur n'a pas répondu dans le délai imparti" : "moteur injoignable",
      }));
    } finally {
      clearTimeout(minuteur);
    }
    if (statut === 401 && essai === 0) { jeton = ""; continue; }   // session morte : on en rouvre une
    break;
  }
  if (statut === 402) {                    // crédits épuisés : on relaie le solde, pas une erreur
    res.statusCode = 402;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    return res.end(texte);
  }
  if (statut === 401) {
    res.statusCode = 401;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    return res.end(JSON.stringify({ erreur: "session absente ou expirée" }));
  }
  if (methode === "POST") texte = memeOrigine(texte, statut);
  res.statusCode = statut;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  return res.end(texte);
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

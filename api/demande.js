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
 */

const DEFAUT = "https://agroguidci-saas.vercel.app";

function base() {
  return (process.env.AGRO_ENGINE_URL || DEFAUT).replace(/\/+$/, "");
}

async function relayer(req, res, methode) {
  const url = base() + "/api/demande";
  const entetes = { Accept: "application/json" };
  const cle = process.env.AGRO_ENGINE_KEY || "";
  if (cle) entetes["X-API-Key"] = cle;
  if (methode === "POST") entetes["Content-Type"] = "application/json";

  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), 25000);   // le moteur répond 202 tout de suite
  try {
    const r = await fetch(url, {
      method: methode,
      headers: entetes,
      body: methode === "POST" ? JSON.stringify(req.body || {}) : undefined,
      signal: ctrl.signal,
    });
    const texte = await r.text();
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
    return relayer(req, res, "POST");
  }
  if (req.method === "GET") return relayer(req, res, "GET");
  res.setHeader("Allow", "GET, POST, OPTIONS");
  res.statusCode = 405;
  return res.end(JSON.stringify({ erreur: "méthode non autorisée" }));
};

/**
 * /api/missions/[id] — suivi d'une mission asynchrone, relayé au moteur AGROGUIDCI.
 *
 * Une coordination dure 30 à 120 s : le navigateur poste sur /api/demande avec
 * {"async": true}, reçoit un identifiant, puis interroge cette route toutes les 3 s.
 * Chaque appel est court : aucune limite de durée de fonction n'est atteinte.
 */

const { baseMoteur, texteBorne } = require("../_lib/engine");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET, OPTIONS");
    res.statusCode = 405;
    return res.end(JSON.stringify({ erreur: "méthode non autorisée" }));
  }
  const id = String((req.query && req.query.id) || "");
  if (!/^j_[A-Za-z0-9]{6,32}$/.test(id)) {
    res.statusCode = 400;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    return res.end(JSON.stringify({ erreur: "identifiant de mission invalide" }));
  }

  const base = baseMoteur();
  if (!base) {
    res.statusCode = 503;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    return res.end(JSON.stringify({ erreur: "Le suivi de mission n'est pas configuré sur cet environnement." }));
  }
  const entetes = { Accept: "application/json" };
  const cle = process.env.AGRO_ENGINE_KEY || "";
  if (cle) entetes["X-API-Key"] = cle;

  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), 15000);
  try {
    const r = await fetch(base + "/api/missions/" + id, {
      headers: entetes, signal: ctrl.signal, redirect: "error",
    });
    const texte = await texteBorne(r);
    res.statusCode = r.status;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    return res.end(texte);
  } catch (e) {
    res.statusCode = 502;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    return res.end(JSON.stringify({ erreur: "moteur injoignable" }));
  } finally {
    clearTimeout(minuteur);
  }
};

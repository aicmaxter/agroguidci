/**
 * GET /api/conversations/{id} — historique et états d'une conversation.
 * La propriété est vérifiée par le moteur : un fil d'une autre session renvoie 404.
 */
const { ID_CONVERSATION, lireCookie, appeler, repondre, erreurMoteur, relayer } = require("../_lib/engine");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return repondre(res, 405, { erreur: "Méthode non autorisée." });
  }
  const id = String(req.query.id || "");
  if (!ID_CONVERSATION.test(id)) return repondre(res, 400, { erreur: "Identifiant invalide." });

  const jeton = lireCookie(req);
  if (!jeton) return repondre(res, 401, { erreur: "Session absente ou expirée." });

  try {
    const r = await appeler(`/api/conversations/${encodeURIComponent(id)}`, { jeton, timeout: 15000 });
    return relayer(res, r);
  } catch (e) {
    return erreurMoteur(res, e);
  }
};

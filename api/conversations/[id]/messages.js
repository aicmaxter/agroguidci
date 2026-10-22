/**
 * POST /api/conversations/{id}/messages — envoie une question au moteur.
 * Le contexte (culture, localité, stade) est validé ici ; le navigateur ne peut
 * jamais désigner un agent, une capacité ou un outil.
 */
const { ID_CONVERSATION, lireCookie, appeler, repondre, erreurMoteur, relayer } = require("../../_lib/engine");

const TEXTE_MAX = 2000;

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return repondre(res, 405, { erreur: "Méthode non autorisée." });
  }
  const id = String(req.query.id || "");
  if (!ID_CONVERSATION.test(id)) return repondre(res, 400, { erreur: "Identifiant invalide." });

  const jeton = lireCookie(req);
  if (!jeton) return repondre(res, 401, { erreur: "Session absente ou expirée." });

  let corps = {};
  try {
    corps = typeof req.body === "string" ? JSON.parse(req.body || "{}") : (req.body || {});
  } catch {
    return repondre(res, 400, { erreur: "Corps JSON invalide." });
  }

  const texte = typeof corps.texte === "string" ? corps.texte.trim() : "";
  if (texte.length < 2 || texte.length > TEXTE_MAX) {
    return repondre(res, 400, { erreur: `Message invalide (2 à ${TEXTE_MAX} caractères).` });
  }

  const propre = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "");
  const charge = {
    texte,
    culture_id: propre(corps.culture_id, 60) || null,
    localite: propre(corps.localite, 120) || null,
    stade: propre(corps.stade, 60) || null,
    idempotency_key: propre(corps.idempotency_key, 100) || null,
  };

  try {
    const r = await appeler(`/api/conversations/${encodeURIComponent(id)}/messages`, {
      method: "POST", corps: charge, jeton, timeout: 20000,
    });
    return relayer(res, r);
  } catch (e) {
    return erreurMoteur(res, e);
  }
};

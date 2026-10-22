/**
 * POST /api/conversations — ouvre une session anonyme puis une conversation.
 * Le jeton de session est posé en cookie HttpOnly : le navigateur ne le lit jamais.
 */
const { lireCookie, ecrireCookie, effacerCookie, appeler, repondre, erreurMoteur } = require("../_lib/engine");

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return repondre(res, 405, { erreur: "Méthode non autorisée." });
  }

  let corps = {};
  try {
    corps = typeof req.body === "string" ? JSON.parse(req.body || "{}") : (req.body || {});
  } catch {
    return repondre(res, 400, { erreur: "Corps JSON invalide." });
  }

  const culture = typeof corps.culture_id === "string" ? corps.culture_id.slice(0, 60) : "";
  const localite = typeof corps.localite === "string" ? corps.localite.slice(0, 120) : "";

  try {
    const jetonExistant = lireCookie(req);
    if (jetonExistant) {
      const essai = await appeler("/api/conversations", {
        method: "POST", corps: { culture_id: culture, localite }, jeton: jetonExistant, timeout: 10000,
      });
      if (essai.status === 201) return finir(res, jetonExistant, essai.donnees);
      if (essai.status !== 401) {
        return repondre(res, 502, { erreur: "Le moteur a répondu de façon inattendue." });
      }
      effacerCookie(res);
    }

    const session = await appeler("/api/sessions", { method: "POST", timeout: 10000 });
    if (session.status !== 200 || !session.donnees || !session.donnees.session_token) {
      return repondre(res, 502, { erreur: "Impossible d'ouvrir une session." });
    }
    const jeton = session.donnees.session_token;

    const conv = await appeler("/api/conversations", {
      method: "POST", corps: { culture_id: culture, localite }, jeton, timeout: 10000,
    });
    if (conv.status !== 201) {
      return repondre(res, 502, { erreur: "Impossible d'ouvrir la conversation." });
    }
    return finir(res, jeton, conv.donnees);
  } catch (e) {
    return erreurMoteur(res, e);
  }
};

function finir(res, jeton, donnees) {
  ecrireCookie(res, jeton);
  return repondre(res, 201, { conversation_id: donnees.conversation_id, expires_at: donnees.expires_at });
}

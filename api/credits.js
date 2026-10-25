/**
 * GET /api/credits — solde réel du compte anonyme.
 *
 * Le solde est calculé par le moteur (journal SQLite des mouvements), jamais par
 * le navigateur. Si l'appelant n'a pas encore de session, une session anonyme est
 * ouverte ici et posée en cookie HttpOnly : le jeton ne transite jamais en clair
 * dans le HTML ni dans le JavaScript de la page.
 */
const { lireCookie, ecrireCookie, appeler, repondre, erreurMoteur } = require("./_lib/engine");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return repondre(res, 405, { erreur: "Méthode non autorisée." });
  }

  try {
    let jeton = lireCookie(req);
    if (jeton) {
      const essai = await appeler("/api/credits", { jeton, timeout: 10000 });
      if (essai.status === 200) return repondre(res, 200, essai.donnees);
      if (essai.status !== 401) return erreurStatus(res, essai);
    }

    const session = await appeler("/api/sessions", { method: "POST", timeout: 10000 });
    if (session.status !== 200 || !session.donnees || !session.donnees.session_token) {
      return repondre(res, 502, { erreur: "Impossible d'ouvrir une session de crédits." });
    }
    jeton = session.donnees.session_token;
    const r = await appeler("/api/credits", { jeton, timeout: 10000 });
    if (r.status !== 200) return erreurStatus(res, r);
    ecrireCookie(res, jeton);
    return repondre(res, 200, r.donnees);
  } catch (e) {
    return erreurMoteur(res, e);
  }
};

function erreurStatus(res, r) {
  if (r.status >= 500) return repondre(res, 502, { erreur: "Le moteur des crédits est indisponible." });
  return repondre(res, r.status, r.donnees || { erreur: "Solde indisponible." });
}

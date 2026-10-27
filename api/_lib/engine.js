/**
 * api/_lib/engine.js — accès serveur au moteur AGROGUIDCI et gestion de la session.
 *
 * Rien de ce module n'est destiné au navigateur : la clé du moteur reste dans
 * l'environnement Vercel (AGRO_ENGINE_KEY) et n'est jamais renvoyée au client.
 */

const DEFAUT_MOTEUR = "https://185-213-27-95.sslip.io";
const MAX_REPONSE = 2 * 1024 * 1024;     // 2 Mo : le moteur ne rend jamais plus
const COOKIE = "agro_session";
const DUREE_COOKIE = 30 * 24 * 3600; // 30 jours glissants
const ID_CONVERSATION = /^cnv_[0-9a-f]{32}$/;

/**
 * Base du moteur, validée une fois pour toutes.
 *
 * Règle : le relais n'envoie la clé du moteur qu'à SON moteur. Une valeur
 * d'environnement absente, mal formée, non HTTPS (hors développement local) ou
 * portant des identifiants dans l'URL est refusée — jamais remplacée par un
 * domaine tiers. `AGRO_RELAIS_STRICT=0` rétablit l'ancien repli, pour revenir en
 * arrière sans redéployer de code.
 */
function baseMoteur(valeur) {
  const brut = String(valeur !== undefined ? valeur : (process.env.AGRO_ENGINE_URL || "")).trim();
  const repli = (process.env.AGRO_RELAIS_STRICT || "1").trim() !== "0";
  if (!brut) {
    if (repli) return "";                 // pas de cible : l'appelant rend 503
    return DEFAUT_MOTEUR;
  }
  let u;
  try {
    u = new URL(brut);
  } catch {
    return repli ? "" : DEFAUT_MOTEUR;
  }
  const local = u.hostname === "127.0.0.1" || u.hostname === "localhost";
  if (u.protocol !== "https:" && !(local && u.protocol === "http:")) return repli ? "" : DEFAUT_MOTEUR;
  if (u.username || u.password) return repli ? "" : DEFAUT_MOTEUR;
  if (u.search || u.hash) return repli ? "" : DEFAUT_MOTEUR;
  const permis = (process.env.AGRO_ENGINE_HOSTS || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (permis.length && !permis.includes(u.hostname)) return repli ? "" : DEFAUT_MOTEUR;
  return (u.origin + u.pathname).replace(/\/+$/, "");
}

/** Lit un corps de réponse en refusant au-delà de MAX_REPONSE octets. */
async function texteBorne(r) {
  const t = await r.text();
  if (t.length > MAX_REPONSE) throw new Error("reponse moteur trop volumineuse");
  return t;
}

const BASE = baseMoteur();


function cle() {
  return process.env.AGRO_ENGINE_KEY || "";
}

/** Lit un cookie nommé dans l'en-tête Cookie. */
function lireCookie(req, nom = COOKIE) {
  const brut = req.headers.cookie || "";
  for (const morceau of brut.split(";")) {
    const [k, ...v] = morceau.trim().split("=");
    if (k === nom) return decodeURIComponent(v.join("="));
  }
  return "";
}

/** Écrit le cookie de session : HttpOnly, Secure, SameSite=Lax. */
function ecrireCookie(res, jeton) {
  res.setHeader("Set-Cookie",
    `${COOKIE}=${encodeURIComponent(jeton)}; Path=/; Max-Age=${DUREE_COOKIE}; HttpOnly; Secure; SameSite=Lax`);
}

function effacerCookie(res) {
  res.setHeader("Set-Cookie", `${COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`);
}

/** Appel interne vers le moteur, avec la clé côté serveur et un délai borné. */
async function appeler(chemin, { method = "GET", corps, jeton, timeout = 25000 } = {}) {
  if (!BASE) {
    const e = new Error("moteur non configuré");
    e.code = "MOTEUR_ABSENT";
    throw e;
  }
  const entetes = { Accept: "application/json" };
  const k = cle();
  if (k) entetes["X-API-Key"] = k;
  if (corps !== undefined) entetes["Content-Type"] = "application/json";
  if (jeton) entetes["X-Session-Token"] = jeton;

  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), timeout);
  try {
    const r = await fetch(BASE + chemin, {
      method,
      headers: entetes,
      body: corps === undefined ? undefined : JSON.stringify(corps),
      signal: ctrl.signal,
      redirect: "error",              // une redirection ne doit pas emmener la clé ailleurs
    });
    const texte = await texteBorne(r);
    let donnees = null;
    try { donnees = texte ? JSON.parse(texte) : null; } catch { donnees = { brut: texte.slice(0, 300) }; }
    return { status: r.status, donnees };
  } finally {
    clearTimeout(minuteur);
  }
}

/** Réponse JSON courte, sans fuite d'information interne. */
function repondre(res, status, corps) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(corps));
}

function erreurMoteur(res, e) {
  if (e && e.code === "MOTEUR_ABSENT") {
    return repondre(res, 503, { erreur: "Le service de réponse n'est pas configuré sur cet environnement." });
  }
  const expire = e && (e.name === "AbortError" || e.code === "ABORT_ERR");
  return repondre(res, expire ? 504 : 502, {
    erreur: expire
      ? "Le moteur n'a pas répondu dans le délai imparti."
      : "Le moteur de l'agent agronome est momentanément indisponible.",
  });
}

/** Traduit une réponse moteur en réponse publique, sans recopier de trace interne. */
function relayer(res, r) {
  if (r.status === 401) return repondre(res, 401, { erreur: "Session absente ou expirée." });
  if (r.status === 404) return repondre(res, 404, { erreur: "Conversation inconnue." });
  if (r.status === 400 || r.status === 422) {
    return repondre(res, 400, { erreur: "Message invalide (2 à 2000 caractères)." });
  }
  if (r.status >= 500) return repondre(res, 502, { erreur: "Le moteur a rencontré une erreur." });
  return repondre(res, r.status, r.donnees);
}

module.exports = { BASE, COOKIE, DUREE_COOKIE, ID_CONVERSATION, MAX_REPONSE, baseMoteur, texteBorne,
                   lireCookie, ecrireCookie, effacerCookie, appeler, repondre, erreurMoteur, relayer };

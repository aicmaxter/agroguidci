/**
 * dev/serveur_local.js — serveur de développement pour la vitrine ET les fonctions api/.
 *
 * Il reproduit ce que fait Vercel : fichiers statiques de web/ + routes /api/* confiées
 * aux mêmes handlers que la production. Permet de tester la chaîne complète
 * (page -> /api/demande -> moteur) sans déployer.
 *
 *   node dev/serveur_local.js
 *
 * Variables :
 *   AGRO_ENGINE_URL   moteur (défaut http://127.0.0.1:8090)
 *   AGRO_ENGINE_KEY   clé d'API du moteur
 *   PORT              port local (défaut 8091)
 */

const http = require("http");
const fs = require("fs");
const path = require("path");

const RACINE = path.resolve(__dirname, "..", "web");
const PORT = Number(process.env.PORT || 8091);

process.env.AGRO_ENGINE_URL = process.env.AGRO_ENGINE_URL || "http://127.0.0.1:8090";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".json": "application/json; charset=utf-8",
};

const routes = {
  "/api/demande": require("../api/demande.js"),
};
const routeMissions = require("../api/missions/[id].js");

function fichier(urlPath) {
  let rel = decodeURIComponent(urlPath.split("?")[0]);
  if (rel === "/" || rel === "") rel = "/index.html";
  if (!path.extname(rel)) rel += ".html";                 // cleanUrls
  const complet = path.join(RACINE, rel);
  if (!complet.startsWith(RACINE)) return null;           // pas de traversée
  return complet;
}

function enrichir(req, res, corps) {
  const u = new URL(req.url, "http://127.0.0.1");
  req.query = Object.fromEntries(u.searchParams.entries());
  req.body = corps;
  res.status = (code) => { res.statusCode = code; return res; };
  res.json = (obj) => {
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify(obj));
    return res;
  };
}

const serveur = http.createServer((req, res) => {
  const chemin = req.url.split("?")[0];
  const morceaux = [];
  req.on("data", (c) => morceaux.push(c));
  req.on("end", async () => {
    const brut = Buffer.concat(morceaux).toString("utf8");
    let corps = undefined;
    if (brut) { try { corps = JSON.parse(brut); } catch (e) { corps = brut; } }
    enrichir(req, res, corps);
    try {
      if (routes[chemin]) return await routes[chemin](req, res);
      const m = chemin.match(/^\/api\/missions\/([^/]+)$/);
      if (m) { req.query.id = decodeURIComponent(m[1]); return await routeMissions(req, res); }
      if (chemin.startsWith("/api/")) {
        res.statusCode = 404;
        return res.end(JSON.stringify({ erreur: "route inconnue" }));
      }
      const f = fichier(req.url);
      if (!f || !fs.existsSync(f) || !fs.statSync(f).isFile()) {
        res.statusCode = 404;
        res.setHeader("Content-Type", "text/plain; charset=utf-8");
        return res.end("404");
      }
      res.setHeader("Content-Type", TYPES[path.extname(f)] || "application/octet-stream");
      return res.end(fs.readFileSync(f));
    } catch (e) {
      res.statusCode = 500;
      res.setHeader("Content-Type", "application/json; charset=utf-8");
      res.end(JSON.stringify({ erreur: "erreur du serveur de dev", detail: String(e).slice(0, 200) }));
    }
  });
});

serveur.listen(PORT, "127.0.0.1", () => {
  console.log(`vitrine + api sur http://127.0.0.1:${PORT} → moteur ${process.env.AGRO_ENGINE_URL}`);
});

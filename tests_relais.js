/**
 * tests_relais.js — cible du relais Vercel : la clé du moteur ne doit jamais
 * partir vers une origine non validée. Exécution : node tests_relais.js
 */
const assert = require("node:assert");
const { baseMoteur } = require("./api/_lib/engine.js");

let ok = 0;
function cas(nom, fn) {
  try {
    fn();
    ok += 1;
    console.log("OK    " + nom);
  } catch (e) {
    console.error("ECHEC " + nom + " — " + e.message);
    process.exitCode = 1;
  }
}

function avecEnv(vars, fn) {
  const avant = {};
  for (const k of Object.keys(vars)) {
    avant[k] = process.env[k];
    if (vars[k] === undefined) delete process.env[k];
    else process.env[k] = vars[k];
  }
  try { return fn(); } finally {
    for (const k of Object.keys(vars)) {
      if (avant[k] === undefined) delete process.env[k];
      else process.env[k] = avant[k];
    }
  }
}

cas("URL https valide acceptée", () =>
  assert.strictEqual(baseMoteur("https://moteur.example/"), "https://moteur.example"));

cas("slash final retiré", () =>
  assert.strictEqual(baseMoteur("https://moteur.example/api///"), "https://moteur.example/api"));

cas("http public refusé", () =>
  avecEnv({ AGRO_RELAIS_STRICT: "1" }, () => assert.strictEqual(baseMoteur("http://moteur.example"), "")));

cas("identifiants dans l'URL refusés", () =>
  avecEnv({ AGRO_RELAIS_STRICT: "1" },
    () => assert.strictEqual(baseMoteur("https://u:p@moteur.example"), "")));

cas("query/hash refusés", () =>
  avecEnv({ AGRO_RELAIS_STRICT: "1" },
    () => assert.strictEqual(baseMoteur("https://moteur.example/?x=1"), "")));

cas("valeur absente → aucune cible (strict)", () =>
  avecEnv({ AGRO_ENGINE_URL: undefined, AGRO_RELAIS_STRICT: "1" }, () => assert.strictEqual(baseMoteur(), "")));

cas("repli non strict = notre moteur, jamais un tiers", () =>
  avecEnv({ AGRO_ENGINE_URL: undefined, AGRO_RELAIS_STRICT: "0" },
    () => assert.strictEqual(baseMoteur(), "https://185-213-27-95.sslip.io")));

cas("hôte hors AGRO_ENGINE_HOSTS refusé", () =>
  avecEnv({ AGRO_RELAIS_STRICT: "1", AGRO_ENGINE_HOSTS: "moteur.example" },
    () => assert.strictEqual(baseMoteur("https://agroguidci-saas.vercel.app"), "")));

cas("hôte dans AGRO_ENGINE_HOSTS accepté", () =>
  avecEnv({ AGRO_RELAIS_STRICT: "1", AGRO_ENGINE_HOSTS: "moteur.example,autre.example" },
    () => assert.strictEqual(baseMoteur("https://autre.example"), "https://autre.example")));

cas("localhost http toléré pour le développement", () =>
  assert.strictEqual(baseMoteur("http://127.0.0.1:8080"), "http://127.0.0.1:8080"));

cas("ancienne cible tierce retirée du code", () => {
  const fs = require("node:fs");
  for (const f of ["api/demande.js", "api/missions/[id].js", "api/_lib/engine.js"]) {
    const src = fs.readFileSync(f, "utf8");
    const sansCommentaires = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.ok(!sansCommentaires.includes("agroguidci-saas"),
      f + " contient encore la cible tierce hors commentaire");
  }
});

console.log("\n" + ok + " test(s) OK");

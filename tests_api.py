"""
tests_api.py — tests de l'API HTTP du moteur (serveur_api.py), sans lancer de mission.

    python tests_api.py

Ce que l'on vérifie (aucun appel réseau, aucun modèle de langage, aucune mission) :
  1. le service refuse de démarrer sans clé d'API (hors mode dev explicite) ;
  2. mauvais en-têtes -> 401 ; texte trop court -> 422 ; corps trop gros -> refus ;
  3. /health et /api/demande (mode d'emploi) répondent sans clé ;
  4. l'enveloppe JSON produite depuis un résultat de mission est complète et
     sérialisable (y compris quand la synthèse est un dict, cas réel du moteur) ;
  5. CORS : seule l'origine déclarée est autorisée.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CLE = "cle-de-test"
os.environ["AGRO_API_KEY"] = CLE
os.environ["AGRO_CORS_ORIGINS"] = "https://agroguidci.vercel.app"
os.environ.pop("AGRO_SANS_AUTH", None)

from fastapi.testclient import TestClient  # noqa: E402

import serveur_api as api  # noqa: E402

resultats = []


def cas(nom: str, ok: bool, detail: str = "") -> None:
    resultats.append((nom, ok, detail))
    print(f"{'OK    ' if ok else 'ECHEC '} {nom:34} {detail}")


# ---------------------------------------------------------------- 1. clé obligatoire
env = dict(os.environ)
env.pop("AGRO_API_KEY", None)
env.pop("AGRO_SANS_AUTH", None)
p = subprocess.run([sys.executable, "-c", "import serveur_api"], cwd=str(ROOT), env=env,
                   capture_output=True, text=True, timeout=120)
cas("demarrage sans cle refuse", p.returncode != 0 and "AGRO_API_KEY" in (p.stdout + p.stderr),
    f"code={p.returncode}")

# ---------------------------------------------------------------- 2. auth / validation
client = TestClient(api.app)

# Aucune mission réelle ne doit partir d'un test : le moteur est remplacé par un double
# qui rend un résultat synthétique (les tests réseau/modèle restent hors de ce fichier).
class _JournalStub:
    mission_id = "mis_test_0001"
    entrees: list = []

    def etat_final(self):
        return "TERMINEE_VERIFIEE"


class _CoordStub:
    def traiter(self, demande, domaines_forces=None, etiquette=None):
        return {"clarification": {"besoin_principal": "besoin de test", "hypotheses": [],
                                  "questions": []},
                "verification": {"statut": "OK", "alertes": []},
                "mission": _JournalStub(), "resultats": {"agronomie": {"status": "completed"}},
                "synthese": {"texte": "## Réponse\n\nRéponse de test.", "avis": [],
                             "sections_manquantes": []},
                "etat_final": "TERMINEE_VERIFIEE"}


api.Coordonnateur = _CoordStub          # le vrai moteur n'est pas sollicité

r = client.post("/api/demande", json={"texte": "analyse mon champ de manioc"})
cas("POST sans cle -> 401", r.status_code == 401, f"code={r.status_code}")

r = client.post("/api/demande", json={"texte": "analyse mon champ de manioc"},
                headers={"X-API-Key": "mauvaise-cle"})
cas("POST mauvaise cle -> 401", r.status_code == 401, f"code={r.status_code}")

r = client.post("/api/demande", json={"texte": "analyse mon champ de manioc"},
                headers={"Authorization": f"Bearer {CLE}"})
cas("Bearer valide accepte", r.status_code != 401, f"code={r.status_code}")

r = client.post("/api/demande", json={"texte": "abc"}, headers={"X-API-Key": CLE})
cas("texte trop court -> 422", r.status_code == 422, f"code={r.status_code}")

r = client.post("/api/demande", json={"texte": "a" * (api.MAX_TEXTE + 10)},
                headers={"X-API-Key": CLE})
cas("texte trop long -> 422", r.status_code == 422, f"code={r.status_code}")

# ---------------------------------------------------------------- 3. endpoints publics
r = client.get("/health")
corps = r.json() if r.status_code == 200 else {}
cas("/health public", r.status_code == 200 and "orchestrateur" in corps,
    f"code={r.status_code} statut={corps.get('status')}")

r = client.get("/api/demande")
cas("mode d'emploi public", r.status_code == 200 and "usage" in r.json(), f"code={r.status_code}")

r = client.get("/api/etat")
cas("/api/etat protege", r.status_code == 401, f"code={r.status_code}")

# ---------------------------------------------------------------- 4. enveloppe
class _Profil:
    def model_dump(self, exclude_none=True):
        return {"localite": "Bouake", "surface_ha": 2.0}


class _Journal:
    mission_id = "mis_test_0001"
    entrees = [
        {"phase": "GOAL", "agent": "AGROGUIDCI", "action": "clarification", "statut": "OK",
         "decision": "CONTINUE", "horodatage": "2026-10-20T10:00:00"},
        {"phase": "VERIFY", "agent": "AGROGUIDCI", "action": "verification", "statut": "OK",
         "decision": "STOP", "horodatage": "2026-10-20T10:01:00"},
    ]

    def etat_final(self):
        return "TERMINEE_VERIFIEE"


resultat = {
    "clarification": {"besoin_principal": "Choisir une culture à Bouaké",
                      "hypotheses": ["budget déclaré"], "questions": ["surface exacte ?"]},
    "verification": {"statut": "OK", "alertes": []},
    "mission": _Journal(),
    "resultats": {"agronomie": {"status": "completed", "result": "..."},
                  "recherche_agricole": {"status": "completed", "result": "..."}},
    "synthese": {"texte": "## Réponse\n\nDu manioc.", "avis": [], "sections_manquantes": [],
                 "finish": "stop"},
    "etat_final": "TERMINEE_VERIFIEE",
}

env_ = api._enveloppe("Question de test", _Profil(), resultat, 12.3)
ok = (env_["id"] == "mis_test_0001" and env_["etat_final"] == "TERMINEE_VERIFIEE"
      and env_["rapport"]["reponse"].startswith("## Réponse")
      and env_["rapport"]["besoin"] == "Choisir une culture à Bouaké"
      and env_["rapport"]["prochaine_action"] == "surface exacte ?"
      and [s["source"] for s in env_["rapport"]["sources"]]
      and len(env_["etapes"]) == 2)
cas("enveloppe complete (synthese dict)", ok,
    f"id={env_['id']} sources={len(env_['rapport']['sources'])}")

try:
    json.dumps(env_, ensure_ascii=False)
    serialisable = True
except (TypeError, ValueError):
    serialisable = False
cas("enveloppe serialisable JSON", serialisable)

# synthèse en texte brut : doit aussi passer
resultat["synthese"] = "## Réponse\n\nDu riz."
env2 = api._enveloppe("Question", None, resultat, 5.0)
cas("enveloppe synthese str", env2["rapport"]["reponse"].startswith("## Réponse"))

# ---------------------------------------------------------------- 5. mode asynchrone
r = client.post("/api/demande", json={"texte": "mission en tache de fond", "async": True},
                headers={"X-API-Key": CLE})
j = r.json() if r.status_code == 202 else {}
cas("POST async -> 202 + id", r.status_code == 202 and j.get("id", "").startswith("j_"),
    f"code={r.status_code} id={j.get('id')}")

jid = j.get("id", "")
etat_final, corps = None, {}
for _ in range(50):                      # le double de moteur répond en quelques ms
    time.sleep(0.1)
    rr = client.get(f"/api/missions/{jid}", headers={"X-API-Key": CLE})
    corps = rr.json() if rr.status_code == 200 else {}
    etat_final = corps.get("statut")
    if etat_final in ("termine", "echec"):
        break
cas("suivi de mission -> termine", etat_final == "termine",
    f"statut={etat_final} duree={corps.get('duree_s')}")
cas("suivi rend la reponse complete",
    bool(corps.get("data", {}).get("rapport", {}).get("reponse")),
    corps.get("data", {}).get("etat_final", "-"))

r = client.get(f"/api/missions/{jid}")
cas("suivi protege par la cle", r.status_code == 401, f"code={r.status_code}")

r = client.get("/api/missions/j_inconnu0000", headers={"X-API-Key": CLE})
cas("mission inconnue -> 404", r.status_code == 404, f"code={r.status_code}")

r = client.get("/api/missions/pirate", headers={"X-API-Key": CLE})
cas("identifiant invalide -> 400", r.status_code == 400, f"code={r.status_code}")

# ---------------------------------------------------------------- 6. CORS
r = client.options("/api/demande", headers={"Origin": "https://agroguidci.vercel.app",
                                          "Access-Control-Request-Method": "POST"})
cas("CORS origine autorisee", r.headers.get("access-control-allow-origin") ==
    "https://agroguidci.vercel.app", r.headers.get("access-control-allow-origin", "-"))

r = client.options("/api/demande", headers={"Origin": "https://exemple-malveillant.tld",
                                          "Access-Control-Request-Method": "POST"})
cas("CORS origine refusee", r.headers.get("access-control-allow-origin") !=
    "https://exemple-malveillant.tld", r.headers.get("access-control-allow-origin", "-"))

# ---------------------------------------------------------------- 6. saturation
api._semaphore._value = 0        # simule un moteur déjà occupé
r = client.post("/api/demande", json={"texte": "question pendant une mission en cours"},
                headers={"X-API-Key": CLE})
cas("moteur sature -> 429", r.status_code == 429, f"code={r.status_code}")
api._semaphore._value = api.MAX_CONCURRENCE

echecs = [n for n, ok, _ in resultats if not ok]
print(f"\n{len(resultats) - len(echecs)}/{len(resultats)} tests OK")
raise SystemExit(1 if echecs else 0)

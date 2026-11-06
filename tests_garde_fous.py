"""tests_garde_fous.py — les garde-fous ajoutés après l'audit de sécurité.

    python tests_garde_fous.py

Ce que l'on vérifie (aucun appel réseau, aucun modèle) :
  1. /api/demande exige une session : sans jeton -> 401, jamais une mission gratuite ;
  2. session sans crédit -> 402, et la mission n'est pas lancée ;
  3. trop de demandes dans la minute depuis la même IP -> 429 ;
  4. quota quotidien par IP -> 429 (le cookie jeté ne rend pas l'usage illimité) ;
  5. trop de mauvaises clés -> 429 (force brute ralentie) ;
  6. /health ne divulgue plus le nom des agents internes.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CLE = "cle-de-test"
os.environ["AGRO_API_KEY"] = CLE
os.environ["AGRO_CORS_ORIGINS"] = "https://agroguidci.vercel.app"
os.environ.pop("AGRO_SANS_AUTH", None)
os.environ["AGRO_CONVERSATIONS_DB"] = str(Path(tempfile.gettempdir()) / "agro-test-garde.db")
os.environ["AGRO_LIMITE_DEMANDE"] = "4"
os.environ["AGRO_LIMITE_GENERAL"] = "5000"
os.environ["AGRO_LIMITE_AUTH"] = "5"
os.environ["AGRO_LIMITE_MISSIONS_JOUR"] = "6"

for suffixe in ("", "-wal", "-shm"):
    Path(os.environ["AGRO_CONVERSATIONS_DB"] + suffixe).unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

import serveur_api as api  # noqa: E402

echecs: list[str] = []


def cas(nom: str, ok: bool, detail: str = "") -> None:
    print(("OK     " if ok else "ECHEC  ") + nom + ("   " + detail if detail else ""))
    if not ok:
        echecs.append(nom)


class _CoordStub:
    appels = 0

    def traiter(self, demande, domaines_forces=None, etiquette=None):
        _CoordStub.appels += 1
        return {"clarification": {"besoin_principal": "test", "hypotheses": [], "questions": []},
                "verification": {"statut": "OK", "alertes": []}, "mission": None,
                "resultats": {"agronomie": {"status": "completed"}},
                "synthese": {"texte": "Réponse de test."},
                "etat_final": "TERMINEE_VERIFIEE"}


api.Coordonnateur = _CoordStub
client = TestClient(api.app)

_SESSION = api.conv.creer_session()
H = {"X-API-Key": CLE, "X-Session-Token": _SESSION["session_token"]}

# 1. session obligatoire
r = client.post("/api/demande", json={"texte": "analyse mon champ de manioc"}, headers={"X-API-Key": CLE})
cas("demande sans session -> 401", r.status_code == 401, f"code={r.status_code}")
cas("aucune mission lancee sans session", _CoordStub.appels == 0, f"appels={_CoordStub.appels}")

# 2. crédits épuisés -> 402
vide = api.conv.creer_session()
for i in range(api.conv.CREDITS_GRATUITS):
    api.conv.consommer(vide["session_id"], f"test:{i}")
r = client.post("/api/demande", json={"texte": "analyse mon champ de manioc"},
                headers={"X-API-Key": CLE, "X-Session-Token": vide["session_token"]})
cas("session sans credit -> 402", r.status_code == 402, f"code={r.status_code}")

# 3. plafond par minute (4/min) — les 4 premières passent, la 5e non
codes = [client.post("/api/demande", json={"texte": "question test"},
                     headers=H).status_code for _ in range(5)]
cas("plafond par minute -> 429", codes[-1] == 429 and 200 in codes, f"codes={codes}")

# 4. quota quotidien par IP : 6 missions/jour. On vide le seau minute entre chaque
#    appel pour être sûr de mesurer le quota JOURNAL, pas le plafond par minute.
etat = []
for _ in range(7):
    api._SEAUX.clear()
    r = client.post("/api/demande", json={"texte": "question quota"},
                    headers=dict(H, **{"X-Client-IP": "41.66.1.9"}))
    etat.append(r.status_code)
cas("quota jour par IP -> 429", etat[-1] == 429 and etat.count(200) == 6, f"codes={etat}")
cas("quota jour compte par IP visee", api.conv.missions_restantes_ip("41.66.1.9", 6) == 0,
    f"restantes={api.conv.missions_restantes_ip('41.66.1.9', 6)}")

# 5. force brute sur la clé
api._SEAUX.clear()
codes = [client.get("/api/etat", headers={"X-API-Key": "fausse"}).status_code for _ in range(7)]
cas("force brute -> 429", codes.count(429) >= 1, f"codes={codes}")

# 6. /health sans noms d'agents
r = client.get("/health")
corps = r.json() if r.status_code == 200 else {}
cas("/health sans noms d'agents", r.status_code == 200 and "agents" not in corps,
    f"cles={sorted(corps)}")

print()
print(f"{'ECHECS' if echecs else 'TOUT OK'} — {len(echecs)} echec(s)")
sys.exit(1 if echecs else 0)

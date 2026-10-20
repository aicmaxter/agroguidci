"""
vps/superviseur.py — processus principal du conteneur moteur AGROGUIDCI.

Il démarre et surveille, dans cet ordre :
    1. six sous-agents   : python expert_agent.py --expert <clé> work
    2. l'agent principal : python coordinateur.py work
    3. l'API HTTP        : python serveur_api.py   (port AGRO_API_PORT, défaut 8080)

L'orchestrateur est un service séparé (conteneur « orchestrateur ») : on attend qu'il
réponde avant d'enrôler les agents. Un enfant qui tombe est relancé avec un recul
progressif ; SIGTERM arrête proprement toute la meute.

    python vps/superviseur.py

Variables utiles :
    AGRO_SANS_AGENTS=1     ne démarre que l'API (agents gérés ailleurs)
    AGRO_ORCH=http://…     orchestrateur à joindre
    ORCH_ATTENTE_S=90      attente maximale de l'orchestrateur au démarrage
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ORCH = (os.environ.get("AGRO_ORCH") or "http://127.0.0.1:8000").rstrip("/")
ATTENTE_ORCH = float(os.environ.get("ORCH_ATTENTE_S", "90"))
SANS_AGENTS = os.environ.get("AGRO_SANS_AGENTS", "") in ("1", "true", "oui")

enfants: dict[str, subprocess.Popen] = {}
arret = False


def journalise(evenement: str, **champs) -> None:
    print(json.dumps({"evenement": evenement, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      **champs}, ensure_ascii=False), flush=True)


def orch_vivant() -> bool:
    try:
        with urllib.request.urlopen(f"{ORCH}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def attendre_orchestrateur() -> bool:
    limite = time.time() + ATTENTE_ORCH
    while time.time() < limite and not arret:
        if orch_vivant():
            journalise("orchestrateur_ok", url=ORCH)
            return True
        time.sleep(2)
    return False


def lancer(nom: str, args: list[str]) -> None:
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen([sys.executable, "-u", *args], cwd=str(ROOT), env=env)
    enfants[nom] = p
    journalise("enfant_demarre", nom=nom, pid=p.pid)


def arreter(*_: object) -> None:
    global arret
    arret = True
    journalise("arret_demande", enfants=len(enfants))
    for nom, p in list(enfants.items()):
        if p.poll() is None:
            p.terminate()
    fin = time.time() + 15
    for nom, p in list(enfants.items()):
        while p.poll() is None and time.time() < fin:
            time.sleep(0.2)
        if p.poll() is None:
            journalise("enfant_tue", nom=nom)
            p.kill()
    journalise("arret_termine")


def plans_de_lancement() -> list[tuple[str, list[str]]]:
    """Les processus à tenir en vie, dans l'ordre de démarrage."""
    plans: list[tuple[str, list[str]]] = []
    if not SANS_AGENTS:
        try:
            from experts import PRINCIPAL, SOUS_AGENTS
            for cle in sorted(SOUS_AGENTS):
                plans.append((f"expert-{cle}", ["expert_agent.py", "--expert", cle, "work"]))
            plans.append(("agent-principal", ["coordinateur.py", "work"]))
            journalise("plan_agents", principal=PRINCIPAL.cle, sous_agents=len(SOUS_AGENTS))
        except Exception as e:                    # pas d'agents : l'API seule démarre
            journalise("plan_agents_erreur", type=type(e).__name__)
    plans.append(("api", ["serveur_api.py"]))
    return plans


def main() -> int:
    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGINT, arreter)

    if not SANS_AGENTS and not attendre_orchestrateur():
        journalise("orchestrateur_injoignable", url=ORCH, attente_s=ATTENTE_ORCH)
        # On démarre quand même l'API : /health dira « degradé », les missions échoueront
        # proprement (aucune réponse inventée).

    plans = plans_de_lancement()
    recul = {nom: 5 for nom, _ in plans}
    for nom, args in plans:
        lancer(nom, args)
        time.sleep(0.5)

    while not arret:
        time.sleep(2)
        for nom, args in plans:
            p = enfants.get(nom)
            if p is None:
                lancer(nom, args)
                continue
            code = p.poll()
            if code is None:
                continue
            if arret:
                break
            journalise("enfant_arrete", nom=nom, code=code, relance_dans_s=recul[nom])
            time.sleep(recul[nom])
            recul[nom] = min(recul[nom] * 2, 60)
            if not arret:
                lancer(nom, args)
        # un enfant stable depuis 60 s retrouve un recul court
        for nom, p in enfants.items():
            if p.poll() is None:
                recul[nom] = 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

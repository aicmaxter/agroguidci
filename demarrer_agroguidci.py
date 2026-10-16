"""
demarrer_agroguidci.py — demarrage et arret du systeme AGROGUIDCI.

Version Python du lanceur (le .ps1 equivalent a ete supprime par la protection
du poste : scripts qui manipulent des processus). Meme role :

    python demarrer_agroguidci.py                 # orchestrateur (si besoin) + 4 agents
    python demarrer_agroguidci.py --sans-coordinateur
    python demarrer_agroguidci.py --arreter       # stoppe les agents AGROGUIDCI
    python demarrer_agroguidci.py --arreter --tout  # stoppe aussi l'orchestrateur
    python demarrer_agroguidci.py --etat          # affiche l'etat puis sort

Les agents demarrent en mode « work » : ils rejoignent le reseau, battent et
executent les taches de leur competence. Les PID sont enregistres dans
out/pids.json pour pouvoir les arreter proprement.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from agrokit import ORCH  # noqa: E402

ORCH_DIR = Path.home() / "orchestrator"
LOGS = ROOT / "logs"
PIDS = ROOT / "out" / "pids.json"
try:                                    # la liste des sous-agents vient de experts.py
    from experts import PRINCIPAL as _PRINCIPAL, SOUS_AGENTS as _SOUS_AGENTS
    EXPERTS = tuple(sorted(_SOUS_AGENTS))
    IDS_AGENTS = {e.agent_id for e in _SOUS_AGENTS.values()} | {_PRINCIPAL.agent_id}
except Exception:                       # repli minimal si experts.py bouge
    EXPERTS = ("techniques_agricoles", "production_animale", "recherche",
               "analyse_donnees", "relation_producteur", "automatisation")
    IDS_AGENTS = {"agro-agronome-01"}
CREATION = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED | NEW_GROUP | NO_WINDOW


def vivant() -> bool:
    try:
        with urllib.request.urlopen(f"{ORCH}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def lancer(nom: str, args: list[str], cwd: Path, env: dict | None = None) -> subprocess.Popen:
    LOGS.mkdir(parents=True, exist_ok=True)
    sortie = open(LOGS / f"{nom}.out.log", "ab", buffering=0)
    erreur = open(LOGS / f"{nom}.err.log", "ab", buffering=0)
    p = subprocess.Popen([sys.executable, "-u", *args], cwd=str(cwd),
                         stdout=sortie, stderr=erreur, stdin=subprocess.DEVNULL,
                         env=env, creationflags=CREATION)
    print(f"  demarre : {nom} (pid {p.pid}, logs/{nom}.out.log)")
    return p


def lire_pids() -> dict:
    if PIDS.exists():
        try:
            return json.loads(PIDS.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def ecrire_pids(pids: dict) -> None:
    PIDS.parent.mkdir(parents=True, exist_ok=True)
    PIDS.write_text(json.dumps(pids, ensure_ascii=False, indent=2), encoding="utf-8")


def tuer(pid: int) -> bool:
    """Arret d'un processus enfant (taskkill : aucune dependance)."""
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except OSError:
        return False


def pid_ecoute(port: int = 8000) -> int | None:
    """PID du processus qui ecoute sur le port (l'orchestrateur n'est pas forcement un enfant)."""
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return None
    for ligne in r.stdout.splitlines():
        if f":{port} " in ligne and "LISTENING" in ligne.upper():
            morceaux = ligne.split()
            if morceaux and morceaux[-1].isdigit():
                return int(morceaux[-1])
    return None


def etat() -> int:
    if not vivant():
        print(f"orchestrateur INJOIGNABLE sur {ORCH}")
        return 2
    try:
        from agrokit import Orchestrateur
        agents = Orchestrateur().agents()
    except Exception as e:
        print(f"orchestrateur joignable mais /agents en echec : {e}")
        return 2
    connus = [a for a in agents if "agroguidci" in (a.get("name") or "").lower()
              or "AGROGUIDCI" in (a.get("name") or "")
              or a.get("agent_id") in IDS_AGENTS]
    print(f"orchestrateur : {ORCH} — {len(agents)} agent(s) declares, "
          f"{sum(1 for a in agents if a['status'] == 'ONLINE')} en ligne")
    for a in agents:
        marque = " *" if a in connus else "  "
        print(f"{marque} {a['status']:<8} {a['name']:<42} "
              f"{','.join(a['capabilities'])[:70]}")
    return 0 if connus else 1


def main() -> int:
    p = argparse.ArgumentParser(description="AgroGUIDCI - lanceur du systeme multi-agents")
    p.add_argument("--arreter", action="store_true")
    p.add_argument("--tout", action="store_true", help="avec --arreter : stoppe aussi l'orchestrateur")
    p.add_argument("--sans-coordinateur", action="store_true")
    p.add_argument("--etat", action="store_true")
    args = p.parse_args()

    if args.etat:
        return etat()

    if args.arreter:
        pids = lire_pids()
        n = 0
        for nom, pid in pids.items():
            if tuer(int(pid)):
                print(f"  arrete : {nom} (pid {pid})")
                n += 1
        if args.tout:
            pid = pid_ecoute(8000)
            if pid and tuer(pid):
                print(f"  arrete : orchestrateur (pid {pid})")
                n += 1
        ecrire_pids({} if args.tout else {})
        print(f"{n} processus arrete(s).")
        return 0

    pids: dict[str, int] = {}

    if not vivant():
        print(f"orchestrateur absent : demarrage sur {ORCH} (bail de tache 900 s)")
        env = {**os.environ, "ORCH_LEASE": "900", "ORCH_DELEGATE_TIMEOUT": "420"}
        proc = lancer("orchestrateur", ["orchestrateur.py"], ORCH_DIR, env=env)
        pids["orchestrateur"] = proc.pid
        limite = time.time() + 60
        while not vivant() and time.time() < limite:
            time.sleep(1)
    if not vivant():
        print(f"ECHEC : orchestrateur injoignable sur {ORCH}")
        ecrire_pids(pids)
        return 2
    print(f"orchestrateur OK : {ORCH}")

    for expert in EXPERTS:
        proc = lancer(f"expert-{expert}", ["expert_agent.py", "--expert", expert, "work"], ROOT)
        pids[f"expert-{expert}"] = proc.pid
    if not args.sans_coordinateur:
        proc = lancer("agent-principal", ["coordinateur.py", "work"], ROOT)
        pids["agent-principal"] = proc.pid

    ecrire_pids(pids)
    time.sleep(8)     # laisse le temps aux agents de s'enroler et de battre
    print()
    etat()
    print("\nExemple :")
    print('  python coordinateur.py --demande "J\'ai 2 ha a Bouake : que cultiver et '
          'comment demarrer un petit elevage ?"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
validation.py — validation humaine des actions sensibles d'AGROGUIDCI.

Principe : un agent n'execute jamais lui-meme une action qui modifie le poste ou
engage le producteur. Il DEPOSE UNE DEMANDE, un operateur la lit et l'approuve,
et c'est l'approbation qui execute l'action — puis on relit le resultat reel.

    python validation.py --lister                 # demandes en attente
    python validation.py --approuver <id>         # execute l'action demandee
    python validation.py --refuser <id> --motif "raison"
    python validation.py --journal                # historique des decisions

Les demandes sont stockees dans data/validations/en_attente/<id>.json (jamais
supprimees : une fois tranchees, elles partent dans approuvees/ ou refusees/).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data" / "validations"
EN_ATTENTE = DATA / "en_attente"
APPROUVEES = DATA / "approuvees"
REFUSEES = DATA / "refusees"
JOURNAL = DATA / "journal.jsonl"

# Registre des actions sensibles : nom d'action -> fonction d'execution reelle.
# Les fonctions sont importees paresseusement (evite les cycles d'import).
def _executeur(action: str):
    from outils import activer_rappels_executer
    return {
        "activer_rappels": activer_rappels_executer,
    }.get(action)


ACTIONS_CONNUES = ("activer_rappels",)


def _horodate() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _journaliser(entree: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")


def demander(action: str, agent: str, motif: str, params: dict | None = None) -> dict:
    """Enregistre une demande de validation. N'execute RIEN."""
    EN_ATTENTE.mkdir(parents=True, exist_ok=True)
    identifiant = f"val_{time.strftime('%Y%m%d-%H%M%S')}_{action}"
    chemin = EN_ATTENTE / f"{identifiant}.json"
    demande = {
        "id": identifiant,
        "action": action,
        "agent": agent,
        "motif": motif,
        "params": params or {},
        "demande_le": _horodate(),
        "etat": "en_attente",
        "execution": None,
    }
    chemin.write_text(json.dumps(demande, ensure_ascii=False, indent=2), encoding="utf-8")
    _journaliser({"ts": _horodate(), "id": identifiant, "action": action, "agent": agent,
                  "etat": "demandee", "motif": motif})
    return demande | {"chemin": str(chemin)}


def lister(etat: str | None = None) -> list[dict]:
    """Demandes en attente (ou approuvees/refusees si etat est precise)."""
    dossiers = {"en_attente": EN_ATTENTE, "approuvees": APPROUVEES, "refusees": REFUSEES}
    sortie: list[dict] = []
    cibles = [dossiers[etat]] if etat in dossiers else [EN_ATTENTE]
    for dossier in cibles:
        if not dossier.exists():
            continue
        for f in sorted(dossier.glob("*.json")):
            try:
                sortie.append(json.loads(f.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
    return sortie


def en_attente() -> list[dict]:
    return lister("en_attente")


def approuver(identifiant: str) -> dict:
    """Execute reellement l'action demandee, puis relit le resultat."""
    chemin = EN_ATTENTE / f"{identifiant}.json"
    if not chemin.exists():
        return {"ok": False, "erreur": f"demande inconnue : {identifiant}"}
    demande = json.loads(chemin.read_text(encoding="utf-8"))
    action = demande.get("action", "")
    executeur = _executeur(action)
    if executeur is None:
        return {"ok": False, "erreur": f"aucun executeur enregistre pour l'action « {action} » "
                                       f"(actions connues : {', '.join(ACTIONS_CONNUES)})"}
    try:
        execution = executeur(demande.get("params", {}))
    except Exception as e:                      # une action qui casse doit etre visible
        execution = {"ok": False, "sortie": f"{type(e).__name__}: {e}"}
    demande |= {"etat": "approuvee", "approuvee_le": _horodate(), "execution": execution}
    APPROUVEES.mkdir(parents=True, exist_ok=True)
    (APPROUVEES / chemin.name).write_text(json.dumps(demande, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    chemin.unlink()
    _journaliser({"ts": _horodate(), "id": identifiant, "action": action,
                  "etat": "approuvee", "execution": execution})
    return {"ok": bool(execution.get("ok")), "demande": demande, "execution": execution}


def refuser(identifiant: str, motif: str = "") -> dict:
    chemin = EN_ATTENTE / f"{identifiant}.json"
    if not chemin.exists():
        return {"ok": False, "erreur": f"demande inconnue : {identifiant}"}
    demande = json.loads(chemin.read_text(encoding="utf-8"))
    demande |= {"etat": "refusee", "refusee_le": _horodate(), "motif_refus": motif}
    REFUSEES.mkdir(parents=True, exist_ok=True)
    (REFUSEES / chemin.name).write_text(json.dumps(demande, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    chemin.unlink()
    _journaliser({"ts": _horodate(), "id": identifiant, "action": demande.get("action"),
                  "etat": "refusee", "motif_refus": motif})
    return {"ok": True, "demande": demande}


def main() -> int:
    p = argparse.ArgumentParser(description="Validation humaine des actions sensibles AGROGUIDCI")
    p.add_argument("--lister", action="store_true")
    p.add_argument("--approuver")
    p.add_argument("--refuser")
    p.add_argument("--motif", default="")
    p.add_argument("--journal", action="store_true")
    args = p.parse_args()

    if args.approuver:
        r = approuver(args.approuver)
        if not r.get("ok"):
            print(f"ECHEC : {r.get('erreur') or r.get('execution')}")
            return 1
        demande, execution = r["demande"], r["execution"]
        print(f"ACTION EXECUTEE — {demande['action']} (demande {demande['id']})")
        print(execution.get("sortie", ""))
        print(f"\netat = {demande['etat']} · journalise dans {JOURNAL}")
        return 0

    if args.refuser:
        r = refuser(args.refuser, args.motif)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1

    if args.journal:
        if not JOURNAL.exists():
            print("aucune decision enregistree.")
            return 0
        for ligne in JOURNAL.read_text(encoding="utf-8").splitlines()[-40:]:
            print(ligne)
        return 0

    demandes = en_attente()
    if not demandes:
        print("Aucune action sensible en attente de validation.")
        print(f"(decisions passees : {JOURNAL})")
        return 0
    print(f"{len(demandes)} action(s) sensible(s) en attente de validation :\n")
    for d in demandes:
        print(f"  id       : {d['id']}")
        print(f"  action   : {d['action']}  (demandee par {d['agent']} le {d['demande_le']})")
        print(f"  motif    : {d['motif'][:200]}")
        for k, v in (d.get("params") or {}).items():
            print(f"  {k:<8} : {str(v)[:160]}")
        print(f"  approuver: python validation.py --approuver {d['id']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

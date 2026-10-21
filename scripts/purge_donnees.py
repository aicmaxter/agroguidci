"""purge_donnees.py — application des durées de conservation (loi n° 2013-450).

Politique publiée dans /confidentialite :
    - questions et rapports de mission ....... 90 jours
    - dossiers producteurs ................... 24 mois après le dernier contact
    - journaux techniques (experts, supervision) 12 mois

Le script ne supprime rien par défaut : il montre ce qu'il ferait. L'effacement
réel exige --executer. Chaque exécution laisse une trace dans out/purge.jsonl.

    python scripts/purge_donnees.py                     # simulation, valeurs par défaut
    python scripts/purge_donnees.py --jours 90 --mois-producteur 24
    python scripts/purge_donnees.py --executer          # efface réellement
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
DATA = ROOT / "data"

RE_HORODATAGE = re.compile(r"^(\d{8})-(\d{6})")
JOURNAUX = (OUT / "journal-experts.jsonl", OUT / "supervision.jsonl")

# Dossiers techniques à ne jamais purger comme des missions
EXCLUS = {"outils", "outils-test", "tests-j2", "tests-r1", "tests-p1", "_archive-run-tronque"}


def _age_jours(chemin: Path) -> float:
    return (time.time() - chemin.stat().st_mtime) / 86400.0


def dossiers_missions(jours: int) -> list[Path]:
    """Dossiers de mission (out/<AAAAMMJJ-HHMMSS...>) plus vieux que la limite."""
    if not OUT.exists():
        return []
    cibles = []
    for d in OUT.iterdir():
        if not d.is_dir() or d.name in EXCLUS:
            continue
        m = RE_HORODATAGE.match(d.name)
        if not m:
            continue
        try:
            debut = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            continue
        if datetime.now() - debut > timedelta(days=jours):
            cibles.append(d)
    return sorted(cibles)


def missions_jsonl(jours: int) -> list[Path]:
    dossier = DATA / "missions"
    if not dossier.exists():
        return []
    return sorted(p for p in dossier.glob("*.jsonl") if _age_jours(p) > jours)


def dossiers_producteurs(mois: int) -> list[Path]:
    dossier = DATA / "producteurs"
    if not dossier.exists():
        return []
    return sorted(p for p in dossier.glob("*.json") if _age_jours(p) > mois * 30.4)


def filtrer_journal(chemin: Path, jours: int, executer: bool) -> tuple[int, int]:
    """Ne garde que les lignes dont l'horodatage est dans la fenêtre. (gardees, supprimees)."""
    if not chemin.exists():
        return 0, 0
    limite = time.time() - jours * 86400
    gardees, supprimees = [], 0
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ligne.strip():
            continue
        try:
            ts = json.loads(ligne).get("ts")
        except ValueError:
            gardees.append(ligne)
            continue
        try:
            horodatage = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").timestamp()
        except (TypeError, ValueError):
            gardees.append(ligne)
            continue
        if horodatage >= limite:
            gardees.append(ligne)
        else:
            supprimees += 1
    if executer and supprimees:
        sauvegarde = chemin.with_suffix(chemin.suffix + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(chemin, sauvegarde)
        chemin.write_text("\n".join(gardees) + ("\n" if gardees else ""), encoding="utf-8")
    return len(gardees), supprimees


def taille(chemins: list[Path]) -> int:
    total = 0
    for p in chemins:
        if p.is_dir():
            total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        elif p.is_file():
            total += p.stat().st_size
    return total


def main() -> int:
    p = argparse.ArgumentParser(description="Purge des données au-delà des durées de conservation")
    p.add_argument("--jours", type=int, default=90, help="âge limite des missions (défaut 90)")
    p.add_argument("--mois-producteur", type=int, default=24, help="âge limite des dossiers producteurs (défaut 24)")
    p.add_argument("--jours-journaux", type=int, default=365, help="âge limite des lignes de journal (défaut 365)")
    p.add_argument("--executer", action="store_true", help="efface réellement (sinon simulation)")
    a = p.parse_args()

    missions = dossiers_missions(a.jours)
    jsonl = missions_jsonl(a.jours)
    producteurs = dossiers_producteurs(a.mois_producteur)

    print(f"Mode : {'EFFACEMENT' if a.executer else 'SIMULATION (aucune suppression)'}")
    print(f"Racine : {ROOT}")
    print(f"Limites : missions {a.jours} j · producteurs {a.mois_producteur} mois · journaux {a.jours_journaux} j\n")

    print(f"Dossiers de mission à purger : {len(missions)} ({taille(missions):,} octets)")
    for d in missions[:10]:
        print(f"  - {d.name}")
    if len(missions) > 10:
        print(f"  … et {len(missions) - 10} autre(s)")

    print(f"\nFichiers de mission .jsonl à purger : {len(jsonl)} ({taille(jsonl):,} octets)")
    for f in jsonl[:10]:
        print(f"  - {f.name}")

    print(f"\nDossiers producteurs au-delà de {a.mois_producteur} mois : {len(producteurs)}")
    for f in producteurs[:10]:
        print(f"  - {f.name}")

    print()
    bilans = {}
    for j in JOURNAUX:
        gardees, supprimees = filtrer_journal(j, a.jours_journaux, a.executer)
        bilans[j.name] = (gardees, supprimees)
        print(f"Journal {j.name} : {supprimees} ligne(s) hors fenêtre, {gardees} conservée(s)")

    if a.executer:
        for d in missions:
            shutil.rmtree(d, ignore_errors=True)
        for f in jsonl + producteurs:
            f.unlink(missing_ok=True)
        print("\nEffacement effectué.")
    else:
        print("\nAucune suppression (relancer avec --executer).")

    trace = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "effacement" if a.executer else "simulation",
        "limites": {"missions_jours": a.jours, "producteurs_mois": a.mois_producteur,
                    "journaux_jours": a.jours_journaux},
        "missions_supprimees": len(missions) if a.executer else 0,
        "missions_candidates": len(missions),
        "jsonl_candidats": len(jsonl),
        "producteurs_candidats": len(producteurs),
        "journaux": {k: {"gardees": v[0], "supprimees": v[1]} for k, v in bilans.items()},
    }
    OUT.mkdir(exist_ok=True)
    with (OUT / "purge.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    print(f"Trace : {OUT / 'purge.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

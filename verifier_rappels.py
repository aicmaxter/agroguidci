"""
verifier_rappels.py — vérificateur des rappels AGROGUIDCI.

Lit `data/automatisations/rappels.json` (écrit par l'agent Automatisation) et
affiche les échéances devenues dues, puis celles à venir. Conçu pour être lancé
à la main ou par une tâche planifiée Windows :

    python verifier_rappels.py                       # rappels échus et à venir
    python verifier_rappels.py --jours 14            # fenêtre d'anticipation
    python verifier_rappels.py --sortie rappels_du_jour.md

Installation de la tâche planifiée (quotidienne, 07:00), à lancer en tant
qu'utilisateur — aucune élévation de privilèges n'est requise :

    schtasks /Create /SC DAILY /ST 07:00 /TN AGROGUIDCI_Rappels ^
      /TR "\"<python.exe>\" \"<ce fichier>\"" /F
    schtasks /Query /TN AGROGUIDCI_Rappels /FO LIST      # vérification
    schtasks /Delete /TN AGROGUIDCI_Rappels /F           # désactivation

L'agent Automatisation génère la commande exacte (chemins compris) et ne
l'exécute que si la mise en place est explicitement demandée.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FICHIER = ROOT / "data" / "automatisations" / "rappels.json"


def charger(chemin: Path) -> list[dict]:
    if not chemin.exists():
        return []
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [r for r in donnees if isinstance(r, dict) and r.get("echeance")]


def main() -> int:
    p = argparse.ArgumentParser(description="Rappels AGROGUIDCI")
    p.add_argument("--jours", type=int, default=7, help="fenêtre d'anticipation en jours")
    p.add_argument("--fichier", default=str(FICHIER))
    p.add_argument("--sortie", default=None, help="écrire aussi la liste dans un fichier markdown")
    args = p.parse_args()

    rappels = charger(Path(args.fichier))
    auj = date.today()
    echus, proches = [], []
    for r in rappels:
        try:
            e = datetime.strptime(r["echeance"], "%Y-%m-%d").date()
        except ValueError:
            continue
        (echus if e <= auj else proches).append((e, r.get("libelle", "(sans libellé)")))
    echus.sort()
    proches.sort()

    lignes = [f"# Rappels AGROGUIDCI — {auj.strftime('%d/%m/%Y %H:%M')}",
              f"Source : {args.fichier} ({len(rappels)} rappel(s) enregistré(s))", ""]
    lignes += ["## Échus / du jour", ""]
    lignes += [f"- [ ] **{e.strftime('%d/%m/%Y')}** — {lib}" for e, lib in echus] or ["- aucun"]
    lignes += ["", f"## À venir (≤ {args.jours} jours)", ""]
    limite = auj.toordinal() + args.jours
    lignes += [f"- [ ] **{e.strftime('%d/%m/%Y')}** — {lib}" for e, lib in proches
               if e.toordinal() <= limite] or [f"- aucun dans les {args.jours} prochains jours"]
    texte = "\n".join(lignes)
    print(texte)
    if args.sortie:
        Path(args.sortie).write_text(texte, encoding="utf-8")
        print(f"\n(écrit dans {args.sortie})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

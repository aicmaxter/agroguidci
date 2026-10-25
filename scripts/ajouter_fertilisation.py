"""ajouter_fertilisation.py — ajoute le bloc « fertilisation » aux fiches cultures.

Chaque culture reçoit une liste d'apports avec produit, dose, moment et méthode.
Deux principes :

  - les fourchettes sont des repères de littérature agronomique ouest-africaine,
    pas des prescriptions : la dose se règle sur une analyse de sol ;
  - quand une donnée manque, on écrit la limite au lieu d'inventer un chiffre.

    python scripts/ajouter_fertilisation.py           # écrit dans content/*.json
    python scripts/ajouter_fertilisation.py --verifier
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FICHIERS = [ROOT / "content" / "cultures-part1.json", ROOT / "content" / "cultures-part2.json"]

NOTE_SOL = ("Doses par hectare de culture pure, à ajuster selon l'analyse de sol. Sans analyse, "
            "rester dans la fourchette basse et fractionner l'azote : c'est le geste qui évite "
            "de brûler la culture et de payer un engrais qui ne sera pas valorisé.")

SOURCES_FUMURE = [
    {"organisme": "FAO", "titre": "Gestion de la fertilité des sols et fumure organique en Afrique de l'Ouest",
     "url": "https://www.fao.org/soils-portal/fr/", "consulte_le": "2026-10-25"},
    {"organisme": "ANADER", "titre": "Fiches techniques cultures vivrières et maraîchères",
     "url": "https://www.anader.ci/", "consulte_le": "2026-10-25"},
]

# produit, dose, moment, méthode, type (organique | mineral | inoculant)
DONNEES: dict[str, dict] = {
    "voandzou": {
        "principe": ("Légumineuse : elle fixe l'azote de l'air. Le raisonnement porte donc sur le "
                     "phosphore et le potassium, pas sur l'urée."),
        "apports": [
            ("Compost ou fumier bien décomposé", "5 à 10 t/ha",
             "2 à 3 semaines avant le semis", "Épandu puis enfoui au labour", "organique"),
            ("Phosphore (P2O5)", "20 à 40 kg/ha",
             "Au semis", "Localisé en poquet, sous la graine (éviter le contact direct)", "mineral"),
            ("Potassium (K2O)", "10 à 20 kg/ha",
             "Au semis", "Seulement si le sol est carencé (cendre de bois possible)", "mineral"),
            ("Azote (N)", "0 kg/ha",
             "—", "Aucun apport : la nodulation fournit l'azote. Un sol vierge gagne à être inoculé.", "mineral"),
        ],
    },
    "fonio": {
        "principe": "Céréale très précoce : l'azote doit être disponible tôt, avant la montaison.",
        "apports": [
            ("Fumier ou compost", "3 à 5 t/ha",
             "Avant le semis", "Épandu et incorporé superficiellement", "organique"),
            ("Azote (N)", "30 à 60 kg/ha",
             "1/2 au tallage, 1/2 à la montaison", "Épandu à la volée sur sol humide", "mineral"),
            ("Phosphore (P2O5)", "15 à 30 kg/ha",
             "Au semis", "Enfoui avec la semence", "mineral"),
        ],
    },
    "sesame": {
        "principe": ("Le sésame valorise mieux un sol correctement pourvu en phosphore. Un excès "
                     "d'azote produit de la tige et peu de capsules."),
        "apports": [
            ("Compost", "5 t/ha", "Avant le semis", "Incorporé au labour", "organique"),
            ("Azote (N)", "25 à 50 kg/ha",
             "1/2 au semis, 1/2 à la floraison", "Épandu entre les rangs", "mineral"),
            ("Phosphore (P2O5)", "20 à 40 kg/ha", "Au semis", "Localisé à côté de la graine", "mineral"),
        ],
    },
    "patatedouce": {
        "principe": ("Culture de tubérisation : c'est le potassium qui fait le rendement. L'azote "
                     "en excès donne du feuillage et des racines fines."),
        "apports": [
            ("Fumier bien décomposé", "10 à 20 t/ha",
             "3 à 4 semaines avant la plantation", "Sur billons, incorporé avant buttage", "organique"),
            ("Potassium (K2O)", "60 à 100 kg/ha",
             "1/2 à la plantation, 1/2 à 30-40 jours", "En bande sur le billon (ou cendre de bois)", "mineral"),
            ("Azote (N)", "30 à 50 kg/ha", "30 jours après plantation", "Épandu puis butté", "mineral"),
            ("Phosphore (P2O5)", "30 à 60 kg/ha", "À la plantation", "En poquet près des boutures", "mineral"),
        ],
    },
    "soja": {
        "principe": ("L'inoculation remplace l'azote : c'est l'apport le plus rentable sur un sol "
                     "qui n'a jamais porté de soja."),
        "apports": [
            ("Inoculant (Bradyrhizobium japonicum)", "1 sachet pour 10 à 20 kg de semence",
             "Au semis, à l'ombre", "Traitement des graines juste avant le semis, sans soleil direct", "inoculant"),
            ("Phosphore (P2O5)", "30 à 60 kg/ha", "Au semis", "En bande ou en poquet", "mineral"),
            ("Potassium (K2O)", "20 à 40 kg/ha", "Au semis", "En bande", "mineral"),
            ("Compost", "3 à 5 t/ha", "Avant le semis", "Incorporé (facultatif si le sol est déjà riche)", "organique"),
        ],
    },
    "igname": {
        "principe": ("L'igname construit une grosse réserve : elle demande une fumure organique "
                     "conséquente dans la butte et un potassium soutenu."),
        "apports": [
            ("Fumier ou compost", "10 à 20 t/ha",
             "3 à 4 semaines avant plantation", "Dans la butte, mélangé à la terre", "organique"),
            ("Azote (N)", "60 à 100 kg/ha",
             "1/3 à 30 jours, 2/3 à 90 jours", "En couronne autour du tuteur", "mineral"),
            ("Phosphore (P2O5)", "30 à 50 kg/ha", "À la plantation", "Dans la butte près du semenceau", "mineral"),
            ("Potassium (K2O)", "60 à 100 kg/ha", "À 60 puis 120 jours", "En bande sur le billon", "mineral"),
        ],
    },
    "plantain": {
        "principe": ("Le bananier est très gourmand en potassium : c'est lui qui remplit le régime. "
                     "Les doses s'expriment par pied, pas par hectare."),
        "apports": [
            ("Fumier composté", "10 à 20 kg/pied/an",
             "Début et milieu de saison des pluies", "En couronne, à 30-40 cm du pied", "organique"),
            ("Azote (N)", "200 à 300 g/pied/an", "En 3 à 4 fois", "En couronne, sol humide", "mineral"),
            ("Potassium (K2O)", "300 à 400 g/pied/an", "En 3 à 4 fois (dont 1 avant floraison)", "En couronne", "mineral"),
            ("Phosphore (P2O5)", "50 à 100 g/pied/an", "Une fois, en début de cycle", "En couronne", "mineral"),
            ("Paillage (résidus, herbe sèche)", "10 à 15 kg/pied/an",
             "Début de saison sèche", "Autour du pied, sans toucher le rejet", "organique"),
        ],
    },
    "poivre": {
        "principe": ("Liane pérenne : la fumure se juge sur l'année, pas sur la campagne. Un excès "
                     "d'azote rend la liane tendre et sensible aux maladies."),
        "apports": [
            ("Fumier composté", "5 à 10 kg/pied/an",
             "Début de saison des pluies", "En couronne, sous le paillage", "organique"),
            ("NPK 15-15-15", "100 à 250 g/pied/an",
             "En 2 à 3 apports (reprise, floraison)", "En couronne, à 20 cm du tuteur", "mineral"),
            ("Potassium (K2O)", "renforcer en fructification", "Après la floraison",
             "Apport complémentaire type sulfate de potasse", "mineral"),
        ],
    },
    "gingembre": {
        "principe": "Le rhizome se remplit en fin de cycle : l'azote tôt, le potassium après la floraison.",
        "apports": [
            ("Fumier ou compost", "10 à 20 t/ha", "Avant la plantation", "Incorporé dans les billons", "organique"),
            ("Azote (N)", "60 à 80 kg/ha", "1/2 à 30 jours, 1/2 à 90 jours", "Épandu entre les rangs", "mineral"),
            ("Phosphore (P2O5)", "40 à 50 kg/ha", "À la plantation", "En poquet près des rhizomes", "mineral"),
            ("Potassium (K2O)", "60 à 80 kg/ha", "À 90 puis 150 jours", "En bande", "mineral"),
        ],
    },
    "curcuma": {
        "principe": "Même famille et même logique que le gingembre : organique au départ, potassium en fin de cycle.",
        "apports": [
            ("Fumier ou compost", "10 à 15 t/ha", "Avant la plantation", "Incorporé dans les billons", "organique"),
            ("Azote (N)", "50 à 75 kg/ha", "1/2 à 30 jours, 1/2 à 75 jours", "Épandu entre les rangs", "mineral"),
            ("Phosphore (P2O5)", "30 à 50 kg/ha", "À la plantation", "En poquet", "mineral"),
            ("Potassium (K2O)", "60 à 90 kg/ha", "À 90 puis 150 jours", "En bande", "mineral"),
        ],
    },
    "piment": {
        "principe": ("Récolte étalée : la fumure se fractionne pour tenir la production jusqu'à la "
                     "fin, sans relancer le feuillage au détriment des fruits."),
        "apports": [
            ("Fumier ou compost", "10 à 20 t/ha", "Avant la plantation", "Incorporé dans les planches", "organique"),
            ("Azote (N)", "60 à 100 kg/ha", "En 3 apports (reprise, floraison, 1re récolte)", "En bande", "mineral"),
            ("Phosphore (P2O5)", "40 à 60 kg/ha", "À la plantation", "En poquet", "mineral"),
            ("Potassium (K2O)", "60 à 100 kg/ha", "Dès la floraison, en 2 fois", "En bande", "mineral"),
            ("Cendre de bois (potasse)", "1 à 2 t/ha", "En complément, avant floraison", "Épandue et incorporée", "organique"),
        ],
    },
}


def bloc(culture_id: str) -> dict | None:
    d = DONNEES.get(culture_id)
    if not d:
        return None
    return {
        "principe": d["principe"],
        "note": NOTE_SOL,
        "apports": [
            {"produit": p, "dose": dose, "moment": moment, "methode": methode, "type": typ}
            for (p, dose, moment, methode, typ) in d["apports"]
        ],
        "sources": SOURCES_FUMURE,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--verifier", action="store_true")
    a = p.parse_args()
    manquants, ecrits = [], 0
    for f in FICHIERS:
        donnees = json.loads(f.read_text(encoding="utf-8"))
        modifie = False
        for cid, c in donnees["cultures"].items():
            b = bloc(cid)
            if not b:
                manquants.append(cid)
                continue
            if c.get("fertilisation") != b:
                if not a.verifier:
                    c["fertilisation"] = b
                    modifie = True
                else:
                    manquants.append(f"{cid} (non à jour)")
        if modifie and not a.verifier:
            f.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ecrits += 1
    if a.verifier:
        if manquants:
            print("fertilisation manquante :", ", ".join(sorted(set(manquants))))
            return 1
        print("fertilisation : à jour pour toutes les cultures")
        return 0
    print(f"fertilisation écrite · fichiers modifiés : {ecrits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

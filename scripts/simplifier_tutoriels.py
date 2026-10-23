"""Ajoute aux 58 étapes de tutoriel un texte en langage courant (`simple`) et un
pictogramme (`icone`), sans toucher au texte source (`texte`) ni aux chiffres.

    python scripts/simplifier_tutoriels.py          # écrit les JSON
    python scripts/simplifier_tutoriels.py --dry    # affiche seulement
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENU = ROOT / "content"

# (simple, icone) par culture et par index d'étape.
SIMPLES: dict[str, list[tuple[str, str]]] = {
    "voandzou": [
        ("Choisissez une terre légère, au soleil, sans creux où l'eau reste.",
         "parcelle"),
        ("Travaillez la terre en surface, nivelez, ajoutez du compost bien mûr si vous en avez.",
         "preparation"),
        ("Gardez les plus grosses graines ; jetez celles qui ont un trou ou de la moisissure.",
         "semence"),
        ("Semez en petits tas espacés, recouvrez de quelques centimètres de terre fine, sur sol humide.",
         "plantation"),
        ("Deux sarclages à la main, sans abîmer les racines ; surveillez les chenilles et l'eau qui stagne.",
         "entretien"),
        ("Arrachez à maturité, séchez les gousses à l'ombre, battez et triez ; gardez au sec.",
         "recolte"),
    ],
    "fonio": [
        ("Émiettez bien la terre et enlevez les restes : la graine est toute petite, "
         "la moindre motte l'empêche de lever.",
         "preparation"),
        ("Semez à la volée, par petites poignées, puis passez légèrement pour enterrer la graine.",
         "plantation"),
        ("Désherbez à la main dès que ça lève : sur le fonio, c'est le travail qui décide de la récolte.",
         "entretien"),
        ("Surveillez les oiseaux et récoltez dès que c'est mûr, pour ne pas perdre les grains au champ.",
         "sante"),
        ("Battez sur une aire propre, séchez jusqu'à ce que les grains ne collent plus, rangez en bidon fermé.",
         "recolte"),
    ],
    "sesame": [
        ("Demandez une variété qui ne s'ouvre pas toute seule (dite non déhiscente) ; sinon, "
         "récoltez très tôt et acceptez des pertes.",
         "semence"),
        ("Terre fine, semez peu profond en lignes, assez espacé pour passer la houe entre les rangs.",
         "plantation"),
        ("Deux sarclages, avant que la culture ne couvre le sol.",
         "entretien"),
        ("Coupez dès que les capsules jaunissent, faites des bottes sur une bâche et laissez sécher.",
         "recolte"),
        ("Battez doucement, vannez, mettez en sacs propres et secs : un lot propre se vend mieux.",
         "stockage"),
    ],
    "patatedouce": [
        ("Faites des buttes hautes, en terre meuble, avec du compost bien mûr.",
         "preparation"),
        ("Prenez des tiges vigoureuses, sans tache ni déformation ; coupez des morceaux de plusieurs nœuds.",
         "semence"),
        ("Plantez en biais, arrosez si la terre est sèche, espacez pour que le feuillage s'étale.",
         "plantation"),
        ("Sarclez tôt, surveillez les maladies, évitez l'eau qui stagne.",
         "entretien"),
        ("Soulevez la butte, triez les racines saines, vendez vite ou transformez en farine.",
         "recolte"),
    ],
    "soja": [
        ("Trouvez l'acheteur ou l'huilerie avant de semer : sans contrat local, le soja se vend mal.",
         "marche"),
        ("Terre fine, semence saine ; inoculez si la parcelle n'en a jamais porté, sur conseil technique.",
         "preparation"),
        ("Semez en lignes, pas trop profond, régulièrement ; en association, gardez les écartements du maïs.",
         "plantation"),
        ("La floraison est la période fragile : pas de manque d'eau, pas de traitement inutile.",
         "sante"),
        ("Récoltez bien sec, séchez, enlevez les graines moisies avant de stocker.",
         "recolte"),
    ],
    "igname": [
        ("Choisissez une terre profonde et qui s'égoutte ; évitez les parcelles tassées et les bas-fonds.",
         "parcelle"),
        ("Faites des buttes hautes avec du fumier ou du compost mûr : c'est le sol qui fait la récolte.",
         "preparation"),
        ("Prenez des semenceaux sains, coupés net ; laissez-les sécher à l'air avant de planter.",
         "semence"),
        ("Posez le semenceau dans la butte, l'œil vers le haut ; tuteurez dès que la tige monte.",
         "plantation"),
        ("Sarclez, buttez pour couvrir les tubercules, surveillez les pourritures.",
         "entretien"),
        ("Creusez sur le côté, soulevez sans arracher ; triez et vendez vite.",
         "recolte"),
    ],
    "plantain": [
        ("Terre profonde et drainée, à l'abri du vent, près de l'eau si la saison sèche est longue.",
         "parcelle"),
        ("Faites de larges trous, mélangez du compost mûr à la terre de surface.",
         "preparation"),
        ("Choisissez des rejets vigoureux, sans tache ni pourriture ; parez les racines et laissez-les sécher.",
         "semence"),
        ("Plantez bien droit, le collet au niveau du sol, puis paillez pour garder l'humidité.",
         "plantation"),
        ("Gardez un seul rejet de remplacement par pied, enlevez les autres, apportez de la matière organique.",
         "entretien"),
        ("Récoltez à maturité laitière, transportez sans choc, vendez vite ou transformez.",
         "recolte"),
    ],
    "poivre": [
        ("Trouvez vos débouchés (épiceries, restaurants, exportateurs) avant de planter : "
         "c'est ce qui limite cette culture en Côte d'Ivoire.",
         "marche"),
        ("Installez des tuteurs solides avant de planter, et faites des trous profonds avec de la matière organique.",
         "preparation"),
        ("Plantez des boutures saines, déjà enracinées, et attachez-les au tuteur dès la mise en terre.",
         "plantation"),
        ("Paillez, gardez un peu d'ombre, drainez : les racines ne doivent jamais baigner dans l'eau.",
         "entretien"),
        ("Cueillez les épis mûrs au fur et à mesure, séchez vite à l'ombre ventilée, stockez étanche.",
         "recolte"),
    ],
    "gingembre": [
        ("Préparez une planche légèrement bombée, en terre meuble, avec du compost mûr : l'eau doit s'écouler.",
         "preparation"),
        ("Choisissez des morceaux fermes avec au moins un bourgeon, sans tache ni moisissure.",
         "semence"),
        ("Enfoncez légèrement, bourgeon vers le haut, espacez pour laisser le feuillage pousser.",
         "plantation"),
        ("Paillez, sarclez légèrement, surveillez les pourritures et l'eau après les pluies.",
         "entretien"),
        ("Récoltez quand les feuilles jaunissent ; vendez frais ou faites sécher et broyez pour garder.",
         "recolte"),
    ],
    "curcuma": [
        ("Faites des buttes hautes, en terre meuble, avec du compost mûr.",
         "preparation"),
        ("Plantez des morceaux de rhizome avec un bourgeon, peu profond, espacés régulièrement.",
         "plantation"),
        ("Paillez, sarclez légèrement, drainez, et n'abusez pas des apports organiques.",
         "entretien"),
        ("Récoltez quand les feuilles jaunissent, soulevez sans blesser, lavez et triez.",
         "recolte"),
        ("Tranchez fin, séchez vite, broyez et rangez à l'abri de la lumière.",
         "stockage"),
    ],
    "piment": [
        ("Semez en pépinière, en terre fine, avec un peu d'ombre et des arrosages réguliers ; "
         "repiquez les plants vigoureux.",
         "semence"),
        ("Préparez une planche drainée, avec du compost mûr et assez d'espace pour que l'air circule.",
         "preparation"),
        ("Repiquez avec la motte, sans casser les racines, et arrosez tout de suite.",
         "plantation"),
        ("Arrosez régulièrement, sarclez, surveillez les pucerons et les maladies.",
         "entretien"),
        ("Récoltez au fur et à mesure, séchez sur une claie, stockez hermétique.",
         "recolte"),
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="affiche sans écrire")
    args = ap.parse_args()
    manquants, total, modifies = [], 0, 0
    for f in sorted(CONTENU.glob("cultures-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        cultures = d.get("cultures") or {}
        touche = False
        for cid, c in cultures.items():
            etapes = c.get("tutoriel") or []
            plan = SIMPLES.get(cid) or []
            if len(plan) != len(etapes):
                manquants.append(f"{cid} : {len(etapes)} étapes, {len(plan)} textes")
                continue
            for etape, (simple, icone) in zip(etapes, plan):
                total += 1
                if etape.get("simple") != simple or etape.get("icone") != icone:
                    etape["simple"] = simple
                    etape["icone"] = icone
                    touche = True
                    modifies += 1
        if touche and not args.dry:
            f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{total} étapes couvertes · {modifies} mises à jour" + (" (dry)" if args.dry else ""))
    for m in manquants:
        print("  INCOMPLET :", m)
    return 1 if manquants else 0


if __name__ == "__main__":
    sys.exit(main())

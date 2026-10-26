"""build_elevage.py — construit le panneau Élevage de la vitrine.

Source de vérité : knowledge/production_animale.md (repères internes, tous formulés
en ordres de grandeur « à confirmer localement »). Aucun vaccin, aucune posologie,
aucun protocole n'est inventé : quand la base ne documente pas, la fiche publie une
phrase d'orientation vétérinaire à la place d'un tableau.

    python scripts/build_elevage.py            # écrit dans web/index.html
    python scripts/build_elevage.py --verifier # signale un écart sans écrire
"""

from __future__ import annotations

import argparse
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "web" / "index.html"
DEBUT, FIN = "<!-- ELEVAGE:DEBUT -->", "<!-- ELEVAGE:FIN -->"

AVERTISSEMENT = ("Calendrier indicatif à confirmer auprès d'un vétérinaire ou du service "
                 "technique de votre zone. Les protocoles peuvent évoluer.")
URGENCE = ("Contactez rapidement un vétérinaire ou le service technique de votre zone. "
           "Isolez les animaux atteints et n'attendez pas une réponse en ligne pour un cas urgent.")
SOURCE_INTERNE = "Base de connaissances AGROGUIDCI (production_animale.md) — à confirmer avec un vétérinaire"

ESPECES = [
    {
        "id": "volaille", "nom": "Volaille", "icone": "volaille",
        "intro": "Poulet de chair, pondeuses et volaille locale améliorée. La poussinière décide de la bande : "
                 "température, densité et eau propre font plus que n'importe quel traitement.",
        "conduite": [
            "Préchauffer le local avant l'arrivée des poussins ; viser un ordre de grandeur de 33 à 35 °C la première semaine, puis baisser de 2 à 3 °C par semaine (à confirmer localement).",
            "Lire le comportement plutôt que le thermomètre : entassés = trop froid, haletants en bordure = trop chaud, répartis = bonne ambiance.",
            "Densité d'engraissement de l'ordre de 8 à 12 sujets/m² en climat chaud ; pondeuses de l'ordre de 5 à 7 sujets/m² en claustration (ordres de grandeur à confirmer).",
            "Aliment en trois phases : démarrage riche et digestible, croissance progressive, finition plus énergétique et moins protéique.",
            "Eau fraîche en permanence : c'est souvent le premier facteur limitant en climat chaud ; abreuvoirs lavés chaque jour.",
            "Ventiler sans courant d'air sur les poussins ; litière humide et odeur d'ammoniac signalent une ventilation insuffisante.",
            "Biosécurité : un seul âge par bâtiment si possible, bottes et matériel dédiés, quarantaine à l'entrée, visiteurs limités.",
            "Tenir un cahier de bande : effectif, mortalité du jour, aliment consommé, traitements et dates. C'est ce carnet qui révèle un problème avant la perte.",
        ],
        "erreurs": [
            "Densifier pour « rentabiliser » le bâtiment : la mortalité et l'indice de consommation se dégradent.",
            "Changer d'aliment sans transition : diarrhées et chute de croissance.",
            "Traiter sans diagnostic : coût inutile et résidus dans les œufs ou la viande.",
        ],
        "tutos": [
            ("Préparer le bâtiment", "Nettoyer, désinfecter, sécher, poser une litière neuve et vérifier le chauffage avant l'arrivée des poussins."),
            ("Mettre en place les poussins", "Eau tiède et aliment fin à disposition, éclairage suffisant, observer la répartition pendant deux heures."),
            ("Régler ambiance et densité", "Ajuster chauffage et ventilation chaque semaine, réduire la densité à mesure que les sujets grandissent."),
            ("Conduire l'alimentation", "Distribuer la ration par phase, noter les quantités, contrôler l'indice de consommation en fin de bande."),
            ("Contrôle sanitaire quotidien", "Retirer les sujets morts, observer fientes, respiration et comportement, consigner la mortalité du jour."),
            ("Collecte et vente", "Œufs ramassés plusieurs fois par jour et stockés à l'ombre ; volaille pesée et vendue sur un marché identifié à l'avance."),
            ("Calculer le coût de production", "Additionner poussins, aliment, litière, eau, électricité, santé et main-d'œuvre, puis diviser par le poids vif vendu."),
        ],
        "sante": {
            "type": "table",
            "rows": [
                ("Maladie de Marek", "J1, au couvoir", "Injection au couvoir", "Une seule fois",
                 "Fait au couvoir : l'éleveur ne refait pas ce vaccin", "Base interne — principe de prophylaxie"),
                ("Newcastle", "J7 à J10", "Eau de boisson ou goutte oculaire", "Rappels avant la sortie de poussinière",
                 "Chaîne du froid, eau propre, sujet en bonne santé", "Base interne — principe de prophylaxie"),
                ("Gumboro (bursite)", "J14", "Eau de boisson", "Rappel selon le protocole du vétérinaire",
                 "Respecter le délai entre vaccins et la qualité de l'eau", "Base interne — principe de prophylaxie"),
                ("Variole aviaire", "Selon le risque local", "Transfixion", "Selon avis vétérinaire",
                 "Décision liée à la pression locale", "Base interne — principe de prophylaxie"),
            ],
            "note": "Les noms de vaccins ci-dessus sont des principes de prophylaxie ; la disponibilité, la souche et le protocole exact se confirment "
                    "auprès du vétérinaire ou du service technique. Aucune posologie, aucun antibiotique n'est indiqué ici.",
        },
    },
    {
        "id": "porcin", "nom": "Porcin", "icone": "porcin",
        "intro": "Cycle court et forte demande urbaine, mais la peste porcine africaine impose une biosécurité stricte : "
                 "aucun vaccin n'existe contre cette maladie.",
        "conduite": [
            "Bâtiment surélevé, sol cimenté et lavable, pente vers l'évacuation, toiture isolée : le porc supporte mal la chaleur.",
            "Séparer les bandes et respecter une circulation du propre vers le sale ; bottes et matériel par zone.",
            "Alimenter selon le stade (démarrage, croissance, finition, truie) et contrôler la qualité des matières premières : moisissures et toxines sont des causes fréquentes d'échec.",
            "Ne jamais donner de restes de cuisine non cuits : c'est un risque majeur de peste porcine africaine.",
            "Eau propre en permanence, abreuvoirs nettoyés ; un porc sans eau mange moins et grossit mal.",
            "Reproduction : truie et verrat en bon état, mise-bas dans une case propre et sèche, surveillance des porcelets dans les premières heures.",
            "Quarantaine de tout animal introduit, contrôle avant achat, pas d'entrée de visiteurs dans les cases.",
            "Tenir un registre : entrées, sorties, mortalité, traitements, poids. Il conditionne la vente et la traçabilité.",
        ],
        "erreurs": [
            "Acheter un animal sans quarantaine pour compléter un lot : c'est le premier vecteur d'introduction.",
            "Utiliser des déchets de cuisine crus.",
            "Confondre « pas de vaccin » et « rien à faire » : la biosécurité est la seule protection contre la PPA.",
        ],
        "tutos": [
            ("Construire les cases", "Sol cimenté, pente, point d'eau, ventilation haute, séparation des bandes."),
            ("Préparer une bande", "Nettoyer, désinfecter, sécher, prévoir litière et matériel dédiés."),
            ("Formuler la ration", "Choisir les matières premières disponibles, équilibrer énergie et protéines, contrôler l'absence de moisissures."),
            ("Conduire au quotidien", "Nourrir à heures fixes, contrôler l'eau, observer appétit, respiration et fientes."),
            ("Contrôle sanitaire", "Prendre la température si un porc reste couché, isoler immédiatement, appeler le vétérinaire en cas de mortalité inhabituelle."),
            ("Vendre au bon poids", "Peser ou estimer, identifier le marché, organiser le transport sans stress ni blessure."),
            ("Calculer le coût de production", "Porcelet, aliment, santé, eau, main-d'œuvre, amortissement du bâtiment."),
        ],
        "sante": {
            "type": "texte",
            "titre": "Un point à connaître absolument",
            "texte": "La peste porcine africaine (PPA) n'a pas de vaccin : aucun protocole vaccinal ne doit être présenté comme protecteur. "
                     "Toute suspicion (mortalité brutale, fièvre, rougeurs, animaux couchés) impose une alerte immédiate au vétérinaire et aux services "
                     "officiels, l'isolement des animaux et l'arrêt des mouvements. Les autres maladies du porc relèvent d'un diagnostic vétérinaire : "
                     "aucun traitement ni dosage n'est proposé ici.",
        },
    },
    {
        "id": "bovin", "nom": "Bovin", "icone": "bovin",
        "intro": "Élevage extensif ou semi-intensif, avec des enjeux sanitaires collectifs : la péripneumonie contagieuse bovine et le charbon "
                 "se traitent d'abord par la prévention et la déclaration.",
        "conduite": [
            "Choisir des animaux adaptés à la zone (races locales et croisements rustiques) plutôt qu'une race exigeante sur un terroir difficile.",
            "Bâtiment ou parc avec ombre, abri contre la pluie, sol non glissant et point d'eau accessible : le stress thermique fait chuter la production.",
            "Pâturage tournant et complémentation en saison sèche ; surveiller la charge pour éviter la dégradation du couvert.",
            "Eau propre à volonté ; un bovin boit beaucoup et supporte mal une eau stagnante.",
            "Reproduction : détection des chaleurs, lutte raisonnée, suivi des gestations, surveillance de la mise-bas.",
            "Hygiène : rotation des parcs, gestion du fumier, contrôle des tiques et des mouches.",
            "Identification des animaux (boucles ou marques) et registre d'élevage : indispensable pour la vaccination et la vente.",
            "Commercialisation planifiée : poids, marché, transport, délai d'attente après traitement.",
        ],
        "erreurs": [
            "Introduire un animal sans quarantaine ni contrôle sanitaire.",
            "Attendre les signes graves avant d'appeler le vétérinaire.",
            "Manipuler une carcasse suspecte de charbon sans précaution.",
        ],
        "tutos": [
            ("Préparer le parc et l'eau", "Clôture, ombre, abreuvoir propre et accessible, sol drainé."),
            ("Conduire le pâturage", "Découper en parcelles, respecter la repousse, complémenter en saison sèche."),
            ("Reproduction", "Observer les chaleurs, noter les dates, préparer la mise-bas."),
            ("Contrôle sanitaire", "Examiner les animaux à distance chaque jour, isoler les malades, consigner."),
            ("Vaccination et déclaration", "Suivre les campagnes du service vétérinaire, déclarer toute suspicion."),
            ("Valoriser la production", "Lait ou viande : choisir la filière avant d'investir, calculer le coût par litre ou par kilo."),
            ("Calculer le coût de production", "Alimentation, santé, gardiennage, eau, amortissement, pertes."),
        ],
        "sante": {
            "type": "table",
            "rows": [
                ("Péripneumonie contagieuse bovine", "Campagne annuelle dans les zones concernées", "Injection (voie selon le vaccin)",
                 "Selon le calendrier des services vétérinaires", "Quarantaine des animaux introduits, déclaration des cas",
                 "Base interne — principes de prévention"),
                ("Charbon bactéridien et symptomatique", "Campagne annuelle selon avis vétérinaire", "Injection",
                 "Selon avis vétérinaire", "Ne jamais manipuler une carcasse suspecte sans précaution",
                 "Base interne — principes de prévention"),
            ],
            "note": "Les dates et la périodicité exactes dépendent des campagnes officielles de votre zone : elles se confirment auprès du vétérinaire "
                    "ou du service technique. Aucun antibiotique ni dosage n'est indiqué ici.",
        },
    },
    {
        "id": "ovin-caprin", "nom": "Ovin et caprin", "iconon": "petit-ruminant", "icone": "petit-ruminant",
        "intro": "Petits ruminants rustiques, adaptés aux zones sèches et à l'élevage familial. La conduite repose sur le pâturage, "
                 "l'abreuvement et la maîtrise de la reproduction.",
        "conduite": [
            "Choisir des animaux de la zone : les races locales résistent mieux à la chaleur et aux parcours pauvres.",
            "Abri simple, sec, ventilé, avec une aire d'exercice ; éviter l'humidité permanente.",
            "Pâturage tournant avec complémentation en saison sèche (fourrage conservé, résidus de culture).",
            "Eau propre chaque jour : un petit ruminant mal abreuvé mange moins.",
            "Reproduction : lutte en saison favorable, suivi des mises-bas, sevrage progressif.",
            "Parasitisme : surveiller l'état corporel et les signes d'anémie, alterner les parcours, traiter sur avis vétérinaire.",
            "Clôture ou gardiennage : la divagation est la première cause de perte et de conflit.",
            "Registre simple : entrées, naissances, ventes, mortalité, traitements.",
        ],
        "erreurs": [
            "Laisser divaguer les animaux en saison des cultures.",
            "Traiter au hasard contre les parasites sans diagnostic ni conseil.",
            "Négliger l'eau en saison sèche.",
        ],
        "tutos": [
            ("Construire l'abri", "Toit, sol sec, ventilation, aire d'exercice, point d'eau."),
            ("Mettre en place le troupeau", "Trier par âge, vermifuger selon avis, identifier les animaux."),
            ("Conduire le pâturage", "Parcelles tournantes, complémentation en saison sèche."),
            ("Reproduction", "Détecter les chaleurs, noter les dates, préparer les mises-bas."),
            ("Contrôle sanitaire", "État corporel, boiteries, diarrhées, toux : isoler et appeler en cas de doute."),
            ("Vente", "Poids, marché, transport, délai d'attente après traitement."),
            ("Coût de production", "Alimentation, santé, gardiennage, pertes."),
        ],
        "sante": {
            "type": "texte",
            "titre": "Vaccination : à confirmer localement",
            "texte": "La peste des petits ruminants peut être couverte par des campagnes de vaccination selon la zone, mais la disponibilité et le "
                     "calendrier ne sont pas documentés ici de façon vérifiée : demandez au vétérinaire ou au service technique quels vaccins sont "
                     "réellement disponibles et à quel moment vacciner. Aucun protocole n'est publié à la place d'une source vérifiée.",
        },
    },
    {
        "id": "pisciculture", "nom": "Pisciculture", "icone": "pisciculture",
        "intro": "Étangs, bacs ou cages : la qualité de l'eau commande tout. Un poisson stressé tombe malade, "
                 "et l'eau se dégrade plus vite qu'on ne le voit.",
        "conduite": [
            "Choisir le site : sol retenant l'eau, pente douce, source ou forage fiable, accès au marché.",
            "Préparer le fond de l'étang (séchage, chaulage selon conseil technique, fertilisation maîtrisée) avant la mise en eau.",
            "Densité adaptée à l'espèce et au renouvellement d'eau : mieux vaut moins de poissons et une eau saine.",
            "Alevins de qualité, acclimatés progressivement à la température de l'étang.",
            "Alimentation régulière et suffisante ; un excès d'aliment pollue l'eau et consomme l'oxygène.",
            "Surveiller l'eau : transparence, odeur, couleur, comportement des poissons en surface le matin.",
            "Filets et matériel dédiés, éviter de déplacer des poissons entre bassins sans précaution.",
            "Pêche, tri, conditionnement et vente organisés à l'avance : le poisson ne se stocke pas longtemps.",
        ],
        "erreurs": [
            "Surdensifier et compter sur l'aliment pour compenser.",
            "Attendre que les poissons viennent en surface pour agir sur l'eau.",
            "Introduire des poissons de provenance inconnue sans contrôle.",
        ],
        "tutos": [
            ("Choisir et préparer le site", "Sol, eau, pente, accès ; séchage et préparation du fond."),
            ("Mettre en eau", "Remplissage, contrôle de la qualité, fertilisation selon conseil."),
            ("Empoissonner", "Alevins de qualité, acclimatation, densité prudente."),
            ("Nourrir", "Ration régulière, observation de la consommation, retrait des restes."),
            ("Surveiller l'eau", "Contrôle visuel quotidien, oxygène le matin, réaction aux pluies."),
            ("Pêcher et vendre", "Filets propres, tri, conditionnement, marché identifié."),
            ("Calculer le coût de production", "Alevins, aliment, eau, main-d'œuvre, amortissement, pertes."),
        ],
        "sante": {
            "type": "texte",
            "titre": "Santé du poisson : prévention avant traitement",
            "texte": "La santé en pisciculture passe par la qualité de l'eau, la densité et l'aliment, pas par des médicaments. Aucun vaccin ni "
                     "traitement n'est publié ici : en cas de mortalité, de lésions ou de comportement anormal, contactez le service technique "
                     "ou un vétérinaire spécialisé avant toute intervention.",
        },
    },
    {
        "id": "apiculture", "nom": "Apiculture", "icone": "apiculture",
        "intro": "Production de miel, artisanale ou semi-moderne. L'encadrement technique reste faible : mieux vaut démarrer petit, "
                 "se former et sécuriser la vente avant d'investir.",
        "conduite": [
            "Installer les ruches à l'écart des passages, avec eau à proximité et flore mellifère disponible.",
            "Travailler avec un équipement de protection complet : voile, gants, enfumoir.",
            "Ouvrir les ruches aux heures chaudes, sans vent, et le moins possible.",
            "Laisser aux colonies assez de miel pour survivre à la saison sèche.",
            "Récolter uniquement les rayons operculés, sans détruire le couvain.",
            "Filtrer et laisser décanter le miel, puis conditionner dans des pots propres et secs.",
            "Surveiller les prédateurs et les vols entre ruches ; réduire les entrées si nécessaire.",
            "Noter les dates de récolte et les quantités pour suivre la progression du rucher.",
        ],
        "erreurs": [
            "Récolter tout le miel : les colonies meurent en saison sèche.",
            "Travailler sans protection ni enfumoir.",
            "Chauffer ou diluer le miel pour gagner du volume.",
        ],
        "tutos": [
            ("Choisir le site", "Éloignement, flore, eau, sécurité des personnes et des animaux."),
            ("Installer les ruches", "Supports surélevés, orientation, protection contre le soleil direct."),
            ("Conduire une visite", "Enfumage doux, ouverture limitée, observation de la reine et des réserves."),
            ("Récolter", "Retrait des hausses, brossage, transport couvert vers le lieu d'extraction."),
            ("Extraire et filtrer", "Matériel propre, filtration, décantation, conditionnement."),
            ("Protéger le rucher", "Surveillance des prédateurs, réduction des entrées, entretien."),
            ("Calculer le coût de production", "Ruches, protection, cire, pots, transport, main-d'œuvre."),
        ],
        "sante": {
            "type": "texte",
            "titre": "Santé des colonies",
            "texte": "Les maladies et parasites des abeilles ne se diagnostiquent pas en ligne. Aucun traitement n'est publié ici : en cas de "
                     "colonies qui dépérissent, de couvain anormal ou de mortalité soudaine, faites appel à un apiculteur expérimenté ou au "
                     "service technique agricole de votre zone.",
        },
    },
    {
        "id": "escargot", "nom": "Escargot", "icone": "escargot",
        "intro": "Élevage d'escargots (achatiniculture) encore peu documenté en Côte d'Ivoire : la demande urbaine existe, "
                 "mais l'accompagnement technique est rare.",
        "conduite": [
            "Partir d'un petit nombre de reproducteurs et vérifier la réglementation locale avant toute commercialisation.",
            "Prévoir un local ombragé, humide et clos, avec un sol meuble et une litière propre.",
            "Alimenter avec des végétaux frais et variés, lavés, sans pesticide.",
            "Maintenir une humidité constante sans excès d'eau stagnante.",
            "Éviter la surdensité : elle favorise la mortalité et les épidémies.",
            "Nettoyer régulièrement et retirer les individus morts immédiatement.",
            "Prévoir la transformation ou la vente rapide : l'escargot se conserve mal sans préparation.",
            "Tenir un registre simple des pontes, des pertes et des ventes.",
        ],
        "erreurs": [
            "Prélever des animaux sauvages sans contrôle sanitaire.",
            "Laisser la litière se putréfier.",
            "Se lancer sans marché ni encadrement identifiés.",
        ],
        "tutos": [
            ("Choisir le local", "Ombre, humidité, clôture, accès à l'eau."),
            ("Préparer le parc", "Sol meuble, litière propre, abris, protection contre les prédateurs."),
            ("Mettre en place les reproducteurs", "Sujets sains, densité prudente, observation."),
            ("Nourrir", "Végétaux frais lavés, apport régulier, retrait des restes."),
            ("Suivre les pontes", "Repérer les pontes, isoler les jeunes, noter les dates."),
            ("Récolter et vendre", "Tri, préparation, marché identifié, respect de la réglementation."),
            ("Calculer le coût de production", "Reproducteurs, aliment, local, main-d'œuvre."),
        ],
        "sante": {
            "type": "texte",
            "titre": "Aucune source vérifiée pour un protocole sanitaire",
            "texte": "Il n'existe pas de protocole sanitaire vérifié et publiable ici pour l'escargot en Côte d'Ivoire. En cas de mortalité "
                     "anormale ou de croissance bloquée, contactez le service technique agricole ou un vétérinaire plutôt que d'appliquer un "
                     "traitement trouvé en ligne.",
        },
    },
]

ICONES = {
    "volaille": '<path d="M4 18c0-4 3-7 7-7h3l2-3 1 3h2l-1 4"/><path d="M8 18v3M14 18v3"/>',
    "porcin": '<path d="M4 15c0-4 3-7 8-7h4l2 3v6H6a2 2 0 0 1-2-2z"/><path d="M18 12h2"/><circle cx="9" cy="12" r="1"/>',
    "bovin": '<path d="M6 20V11l3-3h6l3 3v9"/><path d="M6 9 3 6M18 9l3-3"/><path d="M10 20v-4h4v4"/>',
    "petit-ruminant": '<path d="M7 20v-6l2-4h6l2 4v6"/><path d="M5 8 8 4M19 8l-3-4"/><circle cx="10" cy="12" r="1"/>',
    "pisciculture": '<path d="M4 12c4-5 10-5 14 0-4 5-10 5-14 0Z"/><path d="M18 12l3-3v6z"/><circle cx="9" cy="11" r=".8"/>',
    "apiculture": '<ellipse cx="12" cy="14" rx="5" ry="6"/><path d="M7 12h10M7 16h10"/><path d="M9 8c0-2 1-3 3-3s3 1 3 3"/>',
    "escargot": '<path d="M5 17h11a4 4 0 1 0-4-4c0 2 2 3 3 2"/><path d="M16 17h4"/><circle cx="17" cy="12" r=".8"/>',
}


def e(t: str) -> str:
    return html.escape(str(t or ""), quote=True)


def bloc_espece(esp: dict, premier: bool) -> str:
    sante = esp["sante"]
    if sante["type"] == "table":
        entetes = ("Âge ou période", "Intervention", "Voie", "Fréquence", "Précautions", "Source")
        lignes = "".join(
            "<tr>" + "".join(f"<td>{e(c)}</td>" for c in ligne) + "</tr>" for ligne in sante["rows"])
        corps = f'''
        <div class="table-defilement">
          <table class="table-sante">
            <caption>Vaccinations courantes — {e(esp["nom"])}</caption>
            <thead><tr>{''.join(f"<th scope=col>{e(h)}</th>" for h in entetes)}</tr></thead>
            <tbody>{lignes}</tbody>
          </table>
        </div>
        <p class="sante-note">{e(sante.get("note", ""))}</p>'''
    else:
        corps = f'''
        <div class="sante-texte">
          <h4>{e(sante["titre"])}</h4>
          <p>{e(sante["texte"])}</p>
        </div>'''

    conduite = "".join(f"<li>{e(x)}</li>" for x in esp["conduite"])
    erreurs = "".join(f"<li>{e(x)}</li>" for x in esp["erreurs"])
    tutos = "".join(
        f'<li><span class="tuto-num">{i}</span><div><strong>{e(t)}</strong><p>{e(x)}</p></div></li>'
        for i, (t, x) in enumerate(esp["tutos"], 1))

    return f'''      <article class="espece" id="esp-{esp["id"]}" role="tabpanel" aria-label="{e(esp["nom"])}">
        <header class="espece-tete">
          <span class="espece-ico" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{ICONES[esp["icone"]]}</svg></span>
          <div>
            <h2>{e(esp["nom"])}</h2>
            <p>{e(esp["intro"])}</p>
          </div>
        </header>

        <details class="sous" open>
          <summary>Conduite</summary>
          <div class="sous-corps">
            <ul class="liste-conduite">{conduite}</ul>
            <div class="encart-erreurs">
              <h4>Erreurs de débutant</h4>
              <ul>{erreurs}</ul>
            </div>
            <p class="sources-fiche">Sources : {e(SOURCE_INTERNE)} · mise à jour 2026-10-26</p>
          </div>
        </details>

        <details class="sous">
          <summary>Tutoriels</summary>
          <div class="sous-corps">
            <ol class="liste-tutos">{tutos}</ol>
            <p class="sources-fiche">Série numérotée : bâtiment, mise en place, ration, conduite quotidienne, contrôle sanitaire, valorisation, coût de production.</p>
          </div>
        </details>

        <details class="sous">
          <summary>Santé et vaccins</summary>
          <div class="sous-corps">
            <p class="avertissement-calendrier">{e(AVERTISSEMENT)}</p>
            {corps}
          </div>
        </details>

        <div class="urgence-animale" role="note">
          <strong>Urgence animale</strong>
          <p>{e(URGENCE)}</p>
        </div>
      </article>'''


def construire() -> str:
    nav = "".join(
        f'<a class="espece-lien{" actif" if i == 0 else ""}" href="#esp-{esp["id"]}" role="tab" aria-controls="esp-{esp["id"]}" '
        f'aria-selected="{"true" if i == 0 else "false"}" data-espece="{esp["id"]}">{e(esp["nom"])}</a>'
        for i, esp in enumerate(ESPECES))
    articles = "\n".join(bloc_espece(esp, i == 0) for i, esp in enumerate(ESPECES))
    return f'''{DEBUT}
  <section class="panel" id="panel-elevage" role="tabpanel" aria-label="Élevage" hidden>
    <div class="wrap">
      <div class="panel-intro">
        <span class="eyebrow">Élevage</span>
        <h2>Conduire un élevage, sans improviser la santé</h2>
        <p>
          Sept espèces, trois volets : la conduite, les tutoriels de mise en route et la santé. Les repères chiffrés sont donnés en ordres de
          grandeur à confirmer localement ; la vaccination, les traitements et la déclaration d'une maladie relèvent du vétérinaire.
        </p>
      </div>

      <nav class="especes-barre" role="tablist" aria-label="Espèces">
        {nav}
      </nav>

      <div class="especes-corps">
{articles}
      </div>
    </div>
  </section>
{FIN}'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", action="store_true")
    a = ap.parse_args()

    page = INDEX.read_text(encoding="utf-8")
    bloc = construire()
    if DEBUT in page and FIN in page:
        avant = page.split(DEBUT)[0]
        apres = page.split(FIN, 1)[1]
        nouvelle = avant + bloc + apres
        ecart = page.split(DEBUT, 1)[1].split(FIN, 1)[0].strip() != bloc.split(DEBUT, 1)[1].split(FIN, 1)[0].strip()
    else:
        ancre = '<section class="panel" id="panel-marches"'
        if ancre not in page:
            print("ERREUR : point d'insertion introuvable")
            return 2
        nouvelle = page.replace(ancre, bloc + "\n\n  " + ancre, 1)
        ecart = True

    print(f"élevage : {len(ESPECES)} espèces · écart avec index.html : {'oui' if ecart else 'non'}")
    if a.verifier:
        return 1 if ecart else 0
    INDEX.write_text(nouvelle, encoding="utf-8")
    print(f"{INDEX.name} écrit ({len(nouvelle)} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
permissions.py — matrice d'actions et de permissions d'AGROGUIDCI.

Traduction executable de la PARTIE C des specs (LAB 09 et LAB 18 « permission
refusee ») : avant d'executer un outil ou une action demande par le producteur, le
systeme consulte cette matrice.

    automatique          -> execution permise, journalisee
    validation_humaine   -> l'agent depose une demande (validation.py), n'execute rien
    interdit             -> refus motive : l'agent s'arrete et le dit (ARRETEE_PERMISSION)

Aucun contournement : un agent ne peut pas executer une action « interdit ».
"""

from __future__ import annotations

import re
import unicodedata

MODES = ("automatique", "validation_humaine", "interdit")

# --------------------------------------------------------------------------- PARTIE C
MATRICE: dict[str, dict] = {
    "lire_documents": {
        "mode": "automatique",
        "regle": "Respecter le perimetre d'acces (sources ouvertes, bases internes du projet).",
    },
    "calculer": {
        "mode": "automatique",
        "regle": "Controler unites, doublons et coherence avant de publier un chiffre.",
    },
    "preparer_rapport": {
        "mode": "automatique",
        "regle": "Un brouillon n'est jamais un envoi : ne pas pretendre qu'il a ete transmis.",
    },
    "generer_fichier_local": {
        "mode": "automatique",
        "regle": "Uniquement sur demande, dates explicites, et le fichier produit doit etre relu.",
    },
    "ecrire_base_persistante": {
        "mode": "interdit",
        "regle": "Hors perimetre : aucune ecriture dans une base externe sans droits accordes.",
    },
    "envoyer_message": {
        "mode": "interdit",
        "regle": "Validation humaine obligatoire : aucun envoi automatique a un tiers.",
    },
    "tache_systeme": {
        "mode": "validation_humaine",
        "regle": "Demande explicite, autorisation operateur, puis verification de l'etat reel.",
    },
    "acheter_payer": {
        "mode": "interdit",
        "regle": "Aucune action financiere automatique : validation humaine specifique.",
    },
    "publier": {
        "mode": "interdit",
        "regle": "Aucune publication automatique : validation humaine specifique.",
    },
    "supprimer": {
        "mode": "interdit",
        "regle": "Aucune suppression automatique : validation humaine specifique.",
    },
}

# Nature de chaque outil -> action(s) de la matrice (LAB 05 / PARTIE C).
# DOIT couvrir EXACTEMENT registre `OUTILS` de outils.py : un outil absent d'ici
# est refuse par defaut a l'execution (mode « interdit ») et invisible pour la
# supervision. Le controle est automatique (voir supervision.py --coherence).
NATURE_OUTILS: dict[str, tuple[str, ...]] = {
    "meteo_et_pluies": ("lire_documents",),
    "contexte_documentaire": ("lire_documents",),
    "analyser_tableau": ("calculer", "lire_documents"),
    "calculer_marge": ("calculer",),
    "calculer_agro": ("calculer",),
    "lire_document": ("lire_documents",),
    "registre_producteur": ("preparer_rapport",),
    "calendrier_et_rappels": ("generer_fichier_local",),
    "activer_rappels": ("tache_systeme",),
}

# Intentions interdites reperables dans une demande, avec l'action de la matrice.
INTENTIONS: list[tuple[str, tuple[str, ...], str]] = [
    ("envoyer_message",
     ("envoie", "envoyer", "envoi", "expedie", "expedier", "transmets", "transmettre",
      "adresse", "diffuse", "diffuser", "poste mon", "envoie-le"),
     "envoi d'un message a un tiers"),
    ("publier",
     ("publie", "publier", "publication", "poste sur facebook", "mets en ligne"),
     "publication externe"),
    ("acheter_payer",
     ("achete", "acheter", "commande ", "commander ", "paie", "payer", "virement",
      "transfert d'argent", "mobile money"),
     "achat ou paiement"),
    ("supprimer",
     ("supprime", "supprimer", "efface", "effacer", "vide la base"),
     "suppression de donnees"),
]

# Les brouillons sont autorises : ces tournures disent qu'on ne demande PAS l'envoi.
TOURNURES_BROUILLON = (
    "ecris", "écris", "redige", "rédige", "prepare", "prépare", "propose", "donne-moi le texte",
    "je vais envoyer", "que je vais envoyer", "a envoyer", "à envoyer", "pour envoyer",
    "brouillon", "modele de message", "modèle de message", "copier",
)


def sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "")
                   if unicodedata.category(c) != "Mn").lower()


def verifier(action: str) -> dict:
    """Etat de permission d'une action de la matrice, ou d'un OUTIL (via NATURE_OUTILS).

    Pour un outil, le mode le plus restrictif de ses usages l'emporte.
    """
    if action in NATURE_OUTILS:
        verdicts = [verifier(a) for a in NATURE_OUTILS[action]]
        ordre = {"interdit": 3, "validation_humaine": 2, "automatique": 1}
        pire = max(verdicts, key=lambda v: ordre[v["mode"]])
        return {**pire, "outil": action,
                "usages": {v["action"]: v["mode"] for v in verdicts}}
    entree = MATRICE.get(action)
    if not entree:
        return {"action": action, "mode": "interdit", "autorise": False,
                "demande_validation": False,
                "regle": "Action inconnue de la matrice : refusee par defaut (principe de moindre privilege)."}
    mode = entree["mode"]
    return {"action": action, "mode": mode, "regle": entree["regle"],
            "autorise": mode == "automatique", "demande_validation": mode == "validation_humaine"}


def verifier_outil(nom_outil: str) -> list[dict]:
    """Controle de permission de tous les usages declares d'un outil."""
    return [verifier(a) for a in NATURE_OUTILS.get(nom_outil, ())]


def outil_autorise(nom_outil: str) -> bool:
    return all(v["mode"] == "automatique" for v in verifier_outil(nom_outil))


def _motifs(declencheurs: tuple[str, ...]) -> list[tuple[str, object]]:
    """Motifs de declenchement ancres sur des mots entiers.

    Sans cette borne, un simple mot contenant le radical declenchait un refus :
    « la fiche publiee » (participe) etait lu comme « publie » (action), et une
    question de conseil finissait etiquetee « action interdite ».
    """
    return [(sans_accents(d), re.compile(rf"\b{re.escape(sans_accents(d).strip())}\b"))
            for d in declencheurs if d.strip()]


def intentions_interdites(demande: str) -> list[dict]:
    """Repere les demandes qui exigent une action interdite (envoi, achat...).

    Un brouillon demande explicitement n'est pas un envoi : on ne declenche le refus
    que si la demande d'envoi n'est pas encadree par une tournure de redaction.
    Les motifs sont cherches en mots entiers (voir _motifs).
    """
    t = sans_accents(demande)
    brouillon = any(re.search(rf"\b{re.escape(sans_accents(x).strip())}\b", t)
                    for x in TOURNURES_BROUILLON if x.strip())
    trouvees: list[dict] = []
    for action, declencheurs, libelle in INTENTIONS:
        for brut, motif in _motifs(declencheurs):
            if motif.search(t):
                if action == "envoyer_message" and brouillon:
                    continue        # « ecris-moi un message que j'enverrai » : redaction autorisee
                trouvees.append({"action": action, "libelle": libelle,
                                 "extrait": extrait(t, brut), **verifier(action)})
                break
    return trouvees


def extrait(texte: str, motif: str, largeur: int = 45) -> str:
    i = texte.find(motif)
    return texte[max(0, i - largeur): i + len(motif) + largeur].strip()


def rapport_matrice() -> str:
    lignes = ["| action | mode | regle |", "|---|---|---|"]
    for action, e in MATRICE.items():
        lignes.append(f"| `{action}` | {e['mode']} | {e['regle']} |")
    lignes += ["", "| outil | actions de la matrice |", "|---|---|"]
    for outil, actions in NATURE_OUTILS.items():
        lignes.append(f"| `{outil}` | {', '.join('`' + a + '`' for a in actions)} |")
    return "\n".join(lignes)


if __name__ == "__main__":
    print(rapport_matrice())
    print()
    for phrase in ("Envoie un mail a ma cooperative pour reserver des semences",
                   "Ecris-moi un message a envoyer a ma cooperative",
                   "Supprime les vieux rappels",
                   "Commercialise ma recolte"):
        print(f"{phrase!r:70} -> {[i['action'] for i in intentions_interdites(phrase)]}")

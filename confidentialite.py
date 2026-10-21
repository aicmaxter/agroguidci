"""confidentialite.py — minimisation des données personnelles dans les journaux.

Pourquoi ce module existe
-------------------------
Les journaux (missions, supervision, journal des experts) doivent permettre de
rejouer et d'auditer une réponse sans conserver des données personnelles inutiles.
La loi n° 2013-450 du 19 juin 2013 impose la pertinence et la proportionnalité :
un numéro de téléphone écrit par un producteur n'a pas à traîner dans des lignes
de log pendant un an.

Règle appliquée : on masque AVANT écriture. Le contenu utile au diagnostic
(question, localité, culture, montants) reste lisible ; seuls les identifiants
directs (téléphone, e-mail) sont remplacés par un marqueur.

Ce module ne modifie jamais les données métier (dossier producteur, rapport
remis au producteur) : il ne s'applique qu'aux journaux techniques.

    from confidentialite import masquer
    masquer("appelez-moi au 07 12 34 56 78 ou a koffi@exemple.ci")
"""

from __future__ import annotations

import re

MARQUEUR_TEL = "[téléphone masqué]"
MARQUEUR_MAIL = "[e-mail masqué]"

# E-mail : forme courante, sans capture des espaces.
RE_MAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Téléphone ivoirien : 10 chiffres (0X XX XX XX XX), avec séparateurs courants,
# éventuellement précédé de +225 / 00225. Les nombres plus courts (prix, surfaces,
# surfaces en m2) et les nombres plus longs (identifiants de mission) ne matchent pas.
RE_TEL = re.compile(
    r"(?<![\d.])(?:(?:\+|00)225[\s.\-]?)?"
    r"(?:\d{2}[\s.\-]?){4}\d{2}(?![\d])"
)

# Numéro de compte / IBAN local improvisé : on masque les longues suites de chiffres
# séparées par des espaces au-delà de 12 chiffres (comptes bancaires, références).
RE_LONGUE_SUITE = re.compile(r"(?<![\w_\-])(?:\d[\s\-]?){13,}\d(?!\d)")


def masquer(texte: str) -> str:
    """Masque téléphones et e-mails d'un texte destiné à un journal technique."""
    if not texte:
        return texte or ""
    t = RE_MAIL.sub(MARQUEUR_MAIL, texte)
    t = RE_TEL.sub(MARQUEUR_TEL, t)
    t = RE_LONGUE_SUITE.sub("[numéro masqué]", t)
    return t


def masquer_champs(donnees: dict) -> dict:
    """Applique masquer() aux valeurs texte d'un dictionnaire (journal structuré)."""
    sortie = {}
    for cle, valeur in donnees.items():
        if isinstance(valeur, str):
            sortie[cle] = masquer(valeur)
        elif isinstance(valeur, dict):
            sortie[cle] = masquer_champs(valeur)
        elif isinstance(valeur, list):
            sortie[cle] = [masquer(v) if isinstance(v, str) else v for v in valeur]
        else:
            sortie[cle] = valeur
    return sortie


if __name__ == "__main__":
    exemples = [
        "Mon nom est Koffi, joignable au 07 12 34 56 78",
        "Appelez le +225 01 02 03 04 05",
        "Ecrivez a koffi.kouassi@exemple.ci pour le contrat",
        "Prix 250 000 FCFA pour 2 hectares, rendement 1,5 t/ha",
        "Mission mis_20261021-012420 duree 103 s",
    ]
    for e in exemples:
        print(f"{e}\n  -> {masquer(e)}\n")

"""
verification.py — etape VERIFY de la boucle d'autonomie (LAB 14 / LAB 17).

Un outil qui a tourne ne prouve pas que la mission a reussi. Ce module refait les
controles, avec du code independant de celui qui a produit la reponse :

  1. PRESENCE DES SECTIONS   — la reponse couvre-t-elle ce qui etait demande ?
  2. ARITHMETIQUE            — recette, charges, marge et seuil recalcules depuis
                               le tableau brut produit par l'outil (2e calcul) ;
  3. UNITES ET DEVISES       — tonnes/kg melanges sans conversion, montants sans devise ;
  4. ECHECS D'OUTILS         — marqueurs ECHEC_OUTIL / DONNEE_INSUFFISANTE ;
  5. PERMISSIONS             — aucune action interdite presentee comme faite ;
  6. SOURCES                 — les volets qui affirment des faits portent-ils une source ?

Chaque controle renvoie un statut OK / PARTIEL / ECHEC et des alertes lisibles.
"""

from __future__ import annotations

import re
from pathlib import Path

from outils import MARQUEUR_ECHEC, MARQUEUR_INSUFFISANT

SECTIONS_CLE = ("chiffres", "vigilance", "coordination")


def verifier_volet(texte: str) -> dict:
    """Controle d'un volet de sous-agent.

    Un volet n'a pas a contenir la section « coordination » (c'est la synthese de
    l'agent principal). On verifie la prudence et les marqueurs d'echec, pas une
    structure qui n'appartient qu'a la synthese.
    """
    alertes: list[str] = []
    bas = texte.lower()
    if MARQUEUR_ECHEC in texte:
        for ligne in texte.splitlines():
            if ligne.startswith(MARQUEUR_ECHEC):
                alertes.append(f"echec d'outil declare : {ligne[len(MARQUEUR_ECHEC):].strip()[:120]}")
    if MARQUEUR_INSUFFISANT in texte:
        alertes.append("donnees insuffisantes declarees par un outil : conclusion a ne pas "
                       "presenter comme un resultat")
    for motif in ACTIONS_INTERDITES_FAITES:
        if motif in bas:
            alertes.append(f"action externe evoquee comme faite (« {motif} ») sans validation "
                           "humaine : a corriger avant diffusion")
    if re.search(r"\b\d[\d\s.,]{2,}\s*(FCFA|fcfa)\b", texte) and \
            not any(m in bas for m in ("fait", "a confirmer", "ordre de grandeur", "inconnu",
                                       "calcul", "estimation")):
        alertes.append("montants cites sans etiquette FAIT / A CONFIRMER : la prudence n'est pas "
                       "verifiable")
    if MARQUEUR_ECHEC not in texte and MARQUEUR_INSUFFISANT not in texte and len(texte) < 300:
        alertes.append("volet anormalement court : contenu a verifier")
    return {"statut": "OK" if not alertes else "PARTIEL", "alertes": alertes}

# Verbes qui trahiraient une action externe non autorisee (LAB 09 / PARTIE C).
ACTIONS_INTERDITES_FAITES = (
    "a ete envoye", "a été envoyé", "message envoye", "message envoyé", "courriel envoye",
    "courriel envoyé", "j'ai envoye", "j'ai envoyé", "publie sur", "publié sur",
    "paiement effectue", "paiement effectué", "j'ai paye", "j'ai payé",
    "tache creee", "tâche créée", "j'ai supprime", "j'ai supprimé",
)


def _n(txt: str) -> float | None:
    """Lit un nombre en gerant milliers et decimales : « 1 350 000 », « 1,350,000 », « 1,5 »."""
    t = (txt or "").replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    t = t.replace("FCFA", "").replace("fcfa", "").replace("francs", "").strip()
    if not t:
        return None
    if re.fullmatch(r"-?\d{1,3}(?:[,.]\d{3})+", t):        # milliers groupés (1,350,000 ou 1.350.000)
        t = t.replace(",", "").replace(".", "")
    elif "," in t and "." in t:
        t = t.replace(",", "")                              # « , » = milliers, « . » = décimal
    elif "," in t:
        t = t.replace(",", ".")                             # « , » décimal
    t = t.rstrip(".")
    try:
        return float(t)
    except ValueError:
        return None


def verifier_rentabilite(chemin: Path | str) -> dict:
    """Recalcule recette / marge / seuil depuis le tableau brut de l'outil (2e calcul)."""
    chemin = Path(chemin)
    alertes: list[str] = []
    if not chemin.exists():
        return {"statut": "ECHEC", "alertes": [f"tableau brut introuvable : {chemin}"], "recalcul": None}
    texte = chemin.read_text(encoding="utf-8", errors="replace")
    mq = re.search(r"\|\s*([\d\s.,]+)\s*(kg|tonnes?|t)\s*\|\s*([\d\s.,]+)\s*FCFA/(\w+)", texte)
    mc = re.search(r"Total des charges identifiées\s*:\s*\**([\d\s.,]+)\s*FCFA", texte)
    mm = re.search(r"marge brute\s*:\s*\**\s*([\d\s.,]+)\s*FCFA", texte, flags=re.I)
    ms = re.search(r"au moins\s*\**([\d\s.,]+)\s*(kg|tonnes?|t)\**\s*au prix de\s*([\d\s.,]+)", texte)

    qte = _n(mq.group(1)) if mq else None
    pu = _n(mq.group(3)) if mq else None
    charges = _n(mc.group(1)) if mc else None
    marge_outil = _n(mm.group(1)) if mm else None
    recalcul = None
    if qte and pu:
        if (mq.group(2) or "").lower().startswith("tonne") and (mq.group(4) or "").lower() == "kg":
            alertes.append(f"quantite exprimee en {mq.group(2)} alors que le prix est au kg "
                            f"({mq.group(0).strip()}) — conversion a verifier")
        recette = qte * pu
        recalcul = {"quantite": qte, "prix_unitaire": pu, "recette": recette,
                    "charges": charges, "marge": (recette - charges) if charges else None,
                    "seuil_kg": (charges / pu) if (charges and pu) else None}
        if charges is not None and marge_outil is not None:
            ecart = abs(recalcul["marge"] - marge_outil)
            if ecart > 1.0:
                alertes.append(f"marge annoncee {marge_outil:,.0f} FCFA != marge recalculee "
                               f"{recalcul['marge']:,.0f} FCFA (ecart {ecart:,.0f})")
        if ms and recalcul["seuil_kg"] is not None:
            seuil_outil = _n(ms.group(1))
            if seuil_outil and abs(seuil_outil - recalcul["seuil_kg"]) > 1.0:
                alertes.append(f"seuil annonce {seuil_outil:,.0f} != seuil recalcule "
                               f"{recalcul['seuil_kg']:,.0f}")
    elif "0 FCFA" in texte or recalcul is None:
        if MM := re.search(r"marge brute", texte, flags=re.I):
            alertes.append("une marge est annoncee mais les donnees d'entree n'ont pas pu etre "
                           "relues : verification impossible")
    statut = "OK" if not alertes else "PARTIEL"
    return {"statut": statut, "alertes": alertes, "recalcul": recalcul}


def verifier_texte(texte: str, attendues: tuple[str, ...] = SECTIONS_CLE) -> dict:
    """Controles generiques sur un volet ou une synthese."""
    alertes: list[str] = []
    bas = texte.lower()
    for s in attendues:
        if s not in bas:
            alertes.append(f"section « {s} » absente")
    if MARQUEUR_ECHEC in texte:
        for ligne in texte.splitlines():
            if ligne.startswith(MARQUEUR_ECHEC):
                alertes.append(f"echec d'outil declare : {ligne[len(MARQUEUR_ECHEC):].strip()[:120]}")
    if MARQUEUR_INSUFFISANT in texte:
        alertes.append("donnees insuffisantes declarees par un outil : conclusion a ne pas "
                       "presenter comme un resultat")
    for motif in ACTIONS_INTERDITES_FAITES:
        if motif in bas:
            alertes.append(f"action externe evoquee comme faite (« {motif} ») sans validation "
                           "humaine : a corriger avant diffusion")
    if re.search(r"\b\d[\d\s.,]{2,}\s*(FCFA|fcfa)\b", texte) and "source" not in bas \
            and "calcul" not in bas:
        alertes.append("montants cites sans source ni mention de calcul")
    return {"statut": "OK" if not alertes else "PARTIEL", "alertes": alertes}


def verifier_mission(resultats: dict[str, dict], synthese: str, dossier: Path) -> dict:
    """Verification d'ensemble : chaque volet + recalcul des tableaux outilles."""
    volets = {}
    for capacite, rep in resultats.items():
        texte = rep.get("result") or ""
        statut = rep.get("status")
        v = verifier_volet(texte)
        if statut != "completed":
            v["alertes"].append(f"volet non termine (statut={statut})")
            v["statut"] = "ECHEC"
        volets[capacite] = v
    rentab = None
    for candidat in sorted((dossier / "outils").glob("*/rentabilite.md")):
        rentab = verifier_rentabilite(candidat) | {"fichier": str(candidat)}
        break
    sy = verifier_texte(synthese, attendues=())
    alertes_total = [f"{c} : {a}" for c, v in volets.items() for a in v["alertes"]]
    if rentab and rentab["alertes"]:
        alertes_total += [f"recalcul : {a}" for a in rentab["alertes"]]
    if sy["alertes"]:
        alertes_total += [f"synthese : {a}" for a in sy["alertes"]]
    statuts = [v["statut"] for v in volets.values()] + [sy["statut"]]
    statut = "ECHEC" if "ECHEC" in statuts else ("PARTIEL" if alertes_total else "OK")
    return {"statut": statut, "alertes": alertes_total, "volets": volets,
            "recalcul_rentabilite": rentab, "synthese": sy}


def tableau(verif: dict) -> str:
    lignes = [f"**Statut de verification : {verif['statut']}**", "",
              "| volet | statut | alertes |", "|---|---|---|"]
    for c, v in verif["volets"].items():
        lignes.append(f"| {c} | {v['statut']} | {'; '.join(v['alertes'])[:200] or '—'} |")
    if verif.get("recalcul_rentabilite"):
        r = verif["recalcul_rentabilite"]
        lignes += ["", f"- Recalcul independant de la rentabilite (`{r.get('fichier')}`) : "
                       f"{r['statut']}" + (f" — {'; '.join(r['alertes'])[:200]}" if r["alertes"] else "")]
        if r.get("recalcul"):
            v = r["recalcul"]
            lignes.append(f"  - recette {v['recette']:,.0f} FCFA · charges "
                          f"{(v['charges'] or 0):,.0f} FCFA · marge "
                          f"{(v['marge'] or 0):,.0f} FCFA · seuil "
                          f"{(v['seuil_kg'] or 0):,.1f} kg")
    for a in verif["alertes"]:
        lignes.append(f"- ⚠ {a}")
    if not verif["alertes"]:
        lignes.append("- aucun ecart detecte par les controles automatiques")
    return "\n".join(lignes)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(tableau({"statut": "OK", "alertes": [], "volets": {},
                       "recalcul_rentabilite": verifier_rentabilite(sys.argv[1])}))
    else:
        print("usage: python verification.py <chemin/rentabilite.md>")

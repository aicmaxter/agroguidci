"""
outils.py — outils réels mis à la disposition des agents AGROGUIDCI.

Principe : un outil produit des DONNÉES VRAIES (mesurées, calculées, extraites)
et les remet telles quelles à l'agent. Le modèle de langage raisonne ensuite
dessus, mais il ne fabrique ni la donnée ni le calcul. Si un outil échoue, il le
dit : aucune donnée n'est inventée pour combler le vide.

Réseau utilisé (aucune clé d'API, aucune donnée privée) :
  - Open-Meteo (géocodage, archive ERA5, prévision) → pluie et température réelles
  - Wikipédia FR (API MediaWiki) → contexte documentaire sourcé
  - Banque mondiale (API ouverte) → indicateurs macro Côte d'Ivoire

Chaque outil a la signature (demande, contexte, dossier) -> markdown.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agrokit import _http  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# --- Hotes surchargeables : permet aux tests de rupture (LAB 06 / LAB 18) de
# --- simuler une API indisponible sans toucher au code ni au reseau.
BASE_GEO = os.environ.get("AGRO_GEO_BASE", "https://geocoding-api.open-meteo.com")
BASE_METEO = os.environ.get("AGRO_METEO_BASE", "https://api.open-meteo.com")
BASE_ARCHIVE = os.environ.get("AGRO_ARCHIVE_BASE", "https://archive-api.open-meteo.com")
BASE_WIKI = os.environ.get("AGRO_WIKI_BASE", "https://fr.wikipedia.org")
BASE_WB = os.environ.get("AGRO_WB_BASE", "https://api.worldbank.org")

# Marqueurs stables, lus par l'etape OBSERVE / VERIFY de l'agent principal.
MARQUEUR_ECHEC = "ECHEC_OUTIL:"
MARQUEUR_INSUFFISANT = "DONNEE_INSUFFISANTE:"

# --------------------------------------------------------------------------- utilitaires
VILLES_CI = (
    "abidjan", "yopougon", "abobo", "anyama", "bingerville", "grand-bassam", "dabou", "jacqueville",
    "bonoua", "adzope", "agboville", "alepe", "toumodi", "dimbokro", "bongouanou", "daoukro",
    "yamoussoukro", "bouake", "katiola", "tiebissou", "mbahiakro", "sakassou", "beoumi",
    "korhogo", "ferkessedougou", "boundiali", "kouto", "sinematiali", "mbengue", "dikodougou",
    "odienne", "minignan", "touba", "man", "danane", "biankouma", "seguela", "sifie",
    "daloa", "issia", "vavoua", "zuénoula", "zuénoula", "bonon", "gagnoa", "divo", "lakota",
    "san-pedro", "san pedro", "sassandra", "soubre", "meagui", "gueyo", "duékoué", "duekoue",
    "abengourou", "agnibilekrou", "bondoukou", "bouna", "dabakala", "kong", "niakara",
    "tiassale", "sitadougou", "sikensi", "azaguie", "adjudin",
)


def sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def entete_source(titre: str, url: str) -> str:
    return f"_source : {titre} — relevé le {time.strftime('%d/%m/%Y %H:%M')} — {url}_"


def extraire_localite(texte: str) -> str | None:
    """Repère une localité ivoirienne citée dans le texte (accents ignorés).

    La localité citée EN PREMIER gagne : une région du type « Haut-Sassandra »
    ne doit pas l'emporter sur la ville réellement annoncée (« Daloa »).
    """
    t = sans_accents(texte)
    trouves: list[tuple[int, int, str]] = []
    for v in VILLES_CI:
        i = t.find(v)
        if i < 0:
            continue
        prefixe = t[max(0, i - 10):i]
        if v in ("sassandra", "bandama") and prefixe.rstrip().endswith(("haut-", "bas-", "haut", "bas")):
            continue                       # région, pas une ville : on l'ignore
        trouves.append((i, -len(v), v))
    if trouves:
        return sorted(trouves)[0][2].title()
    m = re.search(r"(?:a|à|vers|sur|depuis)\s+([A-ZÉÈÎÔÛ][\w'’\-éèêôûîàç]+)", texte)
    return m.group(1) if m else None


def _get(url: str, timeout: float = 25.0) -> tuple[int, object]:
    try:
        return _http("GET", url, timeout=timeout, tentatives=2)
    except Exception as e:  # réseau capricieux : on remonte l'échec au lieu de le masquer
        return 0, str(e)


# --------------------------------------------------------------------------- recherche : climat
def meteo_et_pluies(demande: str, contexte: str, dossier: Path) -> str:
    """Pluies des 12 derniers mois + prévision 7 jours + déficit hydrique, pour la localité citée."""
    lieu = extraire_localite(f"{demande}\n{contexte}") or "abidjan"
    c, geo = _get(f"{BASE_GEO}/v1/search?name={quote(lieu)}&count=1&language=fr&format=json")
    if c != 200 or not isinstance(geo, dict) or not geo.get("results"):
        return (f"{MARQUEUR_ECHEC} meteo_et_pluies — geocodage impossible pour « {lieu} » (HTTP {c})\n"
                f"### Meteo — ECHEC OUTIL\nLocalite « {lieu} » non geocodee. "
                "Aucune donnee climatique produite : ne rien affirmer sur la pluie de cette zone.")
    g = geo["results"][0]
    lat, lon = g["latitude"], g["longitude"]
    nom = f"{g['name']} ({g.get('admin1') or g.get('country')})"
    auj = date.today()
    debut, fin = auj - timedelta(days=365), auj - timedelta(days=1)
    base = f"{BASE_ARCHIVE}/v1/archive?latitude={lat}&longitude={lon}"
    c2, arch = _get(f"{base}&start_date={debut}&end_date={fin}"
                    "&daily=precipitation_sum&timezone=Africa%2FAbidjan")
    lignes = [f"### Pluies observées sur 12 mois — {nom} (lat {lat:.3f}, lon {lon:.3f})",
              entete_source("Open-Meteo archive (réanalyse ERA5)",
                            f"https://archive-api.open-meteo.com/v1/archive?...&start_date={debut}&end_date={fin}")]
    mois: dict[str, float] = {}
    jours_pluie = 0
    sec_30 = 0
    if c2 == 200 and isinstance(arch, dict):
        d = arch.get("daily", {})
        for j, p in zip(d.get("time", []), d.get("precipitation_sum", [])):
            if p is None:
                continue
            mois[j[:7]] = round(mois.get(j[:7], 0.0) + float(p), 1)
            if float(p) >= 1.0:
                jours_pluie += 1
        cumul = round(sum(mois.values()), 1)
        lignes += ["", "| mois | pluie cumulée (mm) |", "|---|---|"]
        lignes += [f"| {m} | {v:.1f} |" for m, v in sorted(mois.items())]
        lignes += ["", f"- **Cumul 12 mois : {cumul} mm** · jours avec ≥ 1 mm : {jours_pluie} "
                       f"· moyenne mensuelle observée : {cumul / max(len(mois), 1):.1f} mm"]
        # déficit récent
        recents = [float(p) for j, p in zip(d.get("time", []), d.get("precipitation_sum", []))
                   if p is not None and j >= (auj - timedelta(days=30)).isoformat()]
        if recents:
            cumul_30 = round(sum(recents), 1)
            sec_30 = sum(1 for p in recents if p < 1.0)
            moy = cumul / max(len(mois), 1)
            etat = ("DÉFICIT MARQUÉ : moins de la moitié d'un mois moyen sur les 30 derniers jours"
                    if cumul_30 < moy * 0.5 else "pluviométrie des 30 derniers jours dans la norme de l'année observée")
            lignes += [f"- **30 derniers jours : {cumul_30} mm**, {sec_30} jours sans pluie "
                       f"→ {etat} (référence : moyenne mensuelle observée {moy:.1f} mm)"]
    else:
        lignes += [f"{MARQUEUR_ECHEC} meteo_et_pluies — archive indisponible (HTTP {c2})\n"
                   f"⚠ archive indisponible (HTTP {c2}) : aucune valeur de pluie a afficher."]

    c3, prev = _get(f"{BASE_METEO}/v1/forecast"
                    f"?latitude={lat}&longitude={lon}"
                    "&daily=precipitation_sum,temperature_2m_max,temperature_2m_min"
                    "&timezone=Africa%2FAbidjan&forecast_days=7")
    lignes += ["", "### Prévision 7 jours", entete_source("Open-Meteo prévision",
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&forecast_days=7")]
    if c3 == 200 and isinstance(prev, dict):
        d = prev.get("daily", {})
        lignes += ["", "| date | pluie (mm) | T max (°C) | T min (°C) |", "|---|---|---|---|"]
        cum = 0.0
        for j, p, tmax, tmin in zip(d.get("time", []), d.get("precipitation_sum", []),
                                    d.get("temperature_2m_max", []), d.get("temperature_2m_min", [])):
            p = p or 0.0
            cum += float(p)
            lignes.append(f"| {j} | {p:.1f} | {tmax} | {tmin} |")
        lignes += ["", f"- Pluie attendue sur 7 jours : **{cum:.1f} mm**"]
    else:
        lignes += [f"{MARQUEUR_ECHEC} meteo_et_pluies — prevision indisponible (HTTP {c3})\n"
                   f"⚠ prevision indisponible (HTTP {c3})."]
    lignes += ["", "- Nature de la donnée : modèle météo (réanalyse/prévision), **pas une mesure de "
                   "station** — à croiser avec la station météo la plus proche et l'agent ANADER."]
    (dossier / "meteo.md").write_text("\n".join(lignes), encoding="utf-8")
    return "\n".join(lignes)


# --------------------------------------------------------------------------- recherche : sources
def contexte_documentaire(demande: str, contexte: str, dossier: Path) -> str:
    """Extraits Wikipédia FR + indicateurs Banque mondiale, avec URL et année."""
    mots = [m for m in re.findall(r"[A-Za-zÀ-ÿ]{5,}", sans_accents(f"{demande} {contexte}"))
            if m not in {"producteur", "production", "comment", "vouloir", "pouvoir", "demande",
                         "elevage", "culture", "cultures", "agricole"}][:4]
    requete = " ".join(mots[:3]) or "agriculture Côte d'Ivoire"
    lignes = [f"### Contexte documentaire — recherche : « {requete} »"]
    c, res = _get(f"{BASE_WIKI}/w/api.php?action=query&list=search&format=json&srlimit=3"
                  f"&srsearch={requete.replace(' ', '%20')}")
    titres: list[str] = []
    if c == 200 and isinstance(res, dict):
        for it in res.get("query", {}).get("search", []):
            titres.append(it["title"])
    else:
        lignes += [f"{MARQUEUR_ECHEC} contexte_documentaire — recherche Wikipedia indisponible "
                   f"(HTTP {c})\n⚠ recherche Wikipédia indisponible (HTTP {c})."]
    for titre in titres[:2]:
        c2, ext = _get(f"{BASE_WIKI}/w/api.php?action=query&format=json&prop=extracts"
                       f"&explaintext=1&exintro=1&redirects=1&titles={titre.replace(' ', '%20')}")
        texte = ""
        if c2 == 200 and isinstance(ext, dict):
            for p in (ext.get("query", {}).get("pages", {}) or {}).values():
                texte = (p.get("extract") or "").strip()
        if not texte:
            lignes += [f"- **{titre}** : extrait indisponible."]
            continue
        lignes += ["", f"#### {titre}", f"https://fr.wikipedia.org/wiki/{titre.replace(' ', '_')}",
                   texte[:1100] + ("…" if len(texte) > 1100 else ""),
                   entete_source("Wikipédia FR (API MediaWiki)",
                                 f"{BASE_WIKI}/wiki/{titre.replace(' ', '_')}")]
    lignes += ["", "### Indicateurs macro — Côte d'Ivoire (Banque mondiale, API ouverte)",
               "| indicateur | dernière valeur disponible | année |", "|---|---|---|"]
    for indent, libelle in (("AG.PRD.FOOD.XD", "Indice de production alimentaire (2014-2016 = 100)"),
                            ("AG.LND.AGRI.ZS", "Terres agricoles (% du territoire)"),
                            ("SP.RUR.TOTL.ZS", "Population rurale (% de la population)")):
        c3, wb = _get(f"{BASE_WB}/v2/country/CIV/indicator/{indent}?format=json&per_page=20")
        valeur, annee = None, None
        if c3 == 200 and isinstance(wb, list) and len(wb) > 1:
            for obs in wb[1]:
                if obs.get("value") is not None:
                    valeur, annee = obs["value"], obs.get("date")
                    break
        lignes.append(f"| {libelle} | {valeur if valeur is not None else 'non disponible'} "
                      f"| {annee or '—'} |")
    lignes += [entete_source("Banque mondiale, API ouverte (indicateurs CIV)",
                             f"{BASE_WB}/v2/country/CIV/indicator/AG.PRD.FOOD.XD"),
               "", "- Valeurs macro : contexte, **jamais** un chiffre à utiliser pour une décision "
                   "d'exploitation. Les prix et les rendements se relèvent sur le marché local."]
    (dossier / "sources.md").write_text("\n".join(lignes), encoding="utf-8")
    return "\n".join(lignes)


# --------------------------------------------------------------------------- analyse de données
def _nombre(txt: str) -> float | None:
    """Lit un nombre en gerant milliers et decimales : « 1 350 000 », « 1,350,000 », « 1,5 »."""
    t = (txt or "").replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    t = t.replace("FCFA", "").replace("fcfa", "").replace("francs", "").strip()
    if not t:
        return None
    if re.fullmatch(r"-?\d{1,3}(?:[,.]\d{3})+", t):        # milliers groupés
        t = t.replace(",", "").replace(".", "")
    elif "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    t = t.rstrip(".")
    try:
        return float(t)
    except ValueError:
        return None


def analyser_tableau(demande: str, contexte: str, dossier: Path) -> str:
    """Statistiques descriptives calculées sur un tableau CSV fourni (fichier ou texte)."""
    texte, origine = "", ""
    m = re.search(r"([A-Za-z]:[\\/][^\"'|<>\n]+?\.csv|[\w./\\-]+\.csv)", demande)
    if m:
        chemin = Path(m.group(1))
        if chemin.exists():
            origine = str(chemin)
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            sep = ";" if texte.count(";") >= texte.count(",") else ","
        else:
            # LAB 18 « chemin inconnu » : on dit que le fichier est absent, on n'invente rien.
            return (f"{MARQUEUR_ECHEC} analyser_tableau — fichier cite mais introuvable : {chemin}\n"
                    f"### Analyse de tableau — FICHIER ABSENT\n"
                    f"Le chemin `{chemin}` n'existe pas sur le poste. Aucun contenu ne sera "
                    "invente : demander le fichier (ou les chiffres) au producteur, ou fournir un "
                    "chemin valide.")
    else:
        lignes_csv = [l for l in demande.splitlines()
                      if len(re.findall(r"[;,\t]", l)) >= 1 and len(re.findall(r"-?\d", l)) >= 2]
        if len(lignes_csv) < 3:
            return ("### Analyse de tableau — AUCUNE DONNÉE FOURNIE\n"
                    "Aucun tableau CSV exploitable dans la demande (ni fichier .csv, ni lignes "
                    "séparées par ; ou ,). **Demander au producteur ses chiffres réels** "
                    "(quantités, prix unitaires, charges) : rien ne sera estimé à sa place.")
        texte = "\n".join(lignes_csv)
        origine = "bloc CSV de la demande"
        sep = ";" if texte.count(";") >= texte.count(",") else ","
    try:
        lignes = [l for l in csv.reader(io.StringIO(texte), delimiter=sep) if any(c.strip() for c in l)]
    except csv.Error as e:
        return f"### Analyse de tableau — ÉCHEC DE LECTURE ({e}) : aucune statistique produite."
    if all(_nombre(c) is not None for c in lignes[0] if c.strip()):
        # première ligne entièrement numérique : pas d'en-tête déclaré
        entetes = [f"col{i + 1}" for i in range(len(lignes[0]))]
        corps = lignes
    else:
        entetes, corps = lignes[0], lignes[1:]
    colonnes: dict[str, list[float]] = {}
    for i, nom in enumerate(entetes):
        valeurs = []
        for r in corps:
            if i < len(r):
                v = _nombre(r[i])
                if v is not None:
                    valeurs.append(v)
        if valeurs:
            colonnes[nom.strip() or f"col{i+1}"] = valeurs
    if not colonnes:
        return ("### Analyse de tableau — AUCUNE COLONNE NUMÉRIQUE\n"
                "Le tableau est lisible mais ne contient aucun nombre exploitable.")
    out = [f"### Statistiques calculées ({len(corps)} lignes, origine : {origine})",
           "| colonne | n | min | max | moyenne | médiane | somme |", "|---|---|---|---|---|---|---|"]
    for nom, v in colonnes.items():
        out.append(f"| {nom} | {len(v)} | {min(v):.2f} | {max(v):.2f} | {statistics.fmean(v):.2f} "
                   f"| {statistics.median(v):.2f} | {sum(v):.2f} |")
    if len(colonnes) >= 2:
        noms = list(colonnes)
        out += ["", f"- Colonnes numériques présentes : {len(noms)} → comparaison possible "
                    f"entre « {noms[0]} » et « {noms[1]} » (rapport des sommes : "
                    f"{sum(colonnes[noms[1]]) / max(sum(colonnes[noms[0]]), 1e-9):.3f})."]
    if len(corps) < 5:
        out += ["", "⚠ Moins de 5 lignes : aucune tendance ne peut être déduite de cet échantillon."]
    out += ["", "- Ces valeurs sont calculées sur les données fournies, jamais estimées. "
                "Rappel : corrélation ≠ causalité, et un échantillon d'une seule saison ne prouve rien."]
    (dossier / "analyse.csv").write_text(texte, encoding="utf-8")
    (dossier / "analyse.md").write_text("\n".join(out), encoding="utf-8")
    return "\n".join(out)


def _normaliser(qte: float | None, u_qte: str | None, u_prix: str | None) -> tuple[float | None, str]:
    """Convertit tonnes <-> kg quand quantite et prix ne parlent pas de la meme unite.

    Sans cela, « 2 tonnes a 300 FCFA le kg » se lit 2 x 300 = 600 FCFA (vu en vrai).
    """
    if qte is None:
        return None, ""
    a, b = (u_qte or "").lower(), (u_prix or "").lower()
    tonnes = ("tonne", "tonnes", "t")
    if a in tonnes and b == "kg":
        return qte * 1000.0, f"converti de {qte:g} {a} en kg"
    if a == "kg" and b in tonnes:
        return qte / 1000.0, f"converti de {qte:g} kg en tonnes"
    return qte, ""


def calculer_marge(demande: str, contexte: str, dossier: Path) -> str:
    """Arithmétique de marge : recette, charges, marge, seuil de rentabilité. Tout est calculé ici."""
    t = f"{demande}\n{contexte}"
    unite = r"(kg|tonnes?|litres?|sacs?|sujets?|poulets?|t[êe]tes?|bottes?|tas?|pi[eè]ces?)"
    couples = []
    # 1) couple explicite : « 800 kg de maïs à 250 FCFA » / « 2 tonnes à 300 FCFA le kg »
    for m in re.finditer(r"(\d[\d\s.,]*)\s*" + unite + r"\b[^\d\n]{0,30}?"
                         r"(\d[\d\s.,]{1,})\s*(?:FCFA|fcfa|francs)"
                         r"(?:\s*(?:/|par|le)\s*(kg|tonnes?|litres?|sacs?|sujets?|poulets?|"
                         r"t[êe]tes?|pi[eè]ces?))?", t, flags=re.I):
        qte, pu = _nombre(m.group(1)), _nombre(m.group(3))
        qte, note = _normaliser(qte, m.group(2), m.group(4))
        if qte and pu and qte > 0 and pu > 0:
            unite_eff = m.group(4) if note else m.group(2)      # apres conversion : unite du prix
            couples.append((qte, pu, unite_eff, m.group(4) or unite_eff,
                            m.group(0).strip() + (f" [{note}]" if note else "")))
    # 2) quantité et prix unitaire déclarés séparément dans la demande
    if not couples:
        mq = re.search(r"(\d[\d\s.,]*)\s*" + unite + r"\b", t, flags=re.I)
        mp = re.search(r"(?:prix|à|a|le|chaque)\s*(?:unitaire\s*)?(?:de\s*)?(\d[\d\s.,]{1,})\s*"
                       r"(?:FCFA|fcfa|francs)"
                       r"(?:\s*(?:/|par|le)\s*(kg|tonnes?|litres?|sacs?|sujets?|poulets?|"
                       r"t[êe]tes?|pi[eè]ces?))?", t, flags=re.I)
        if mq and mp:
            qte, pu = _nombre(mq.group(1)), _nombre(mp.group(1))
            qte, note = _normaliser(qte, mq.group(2), mp.group(2))
            if qte and pu and qte > 0 and pu > 0:
                unite_eff = mp.group(2) if note and mp.group(2) else mq.group(2)
                couples.append((qte, pu, unite_eff, mp.group(2) or unite_eff,
                                f"{mq.group(0).strip()} / {mp.group(0).strip()}"
                                + (f" [{note}]" if note else "")))
    # charges : « charges 180000 » ou « 180000 FCFA de charges », mots proches du montant
    charges, vus = [], set()
    for motif in (r"(charges?|co[ûu]ts?|d[ée]penses?|budget|investissement|achat|entretien)"
                  r"[^.\n]{0,15}?(\d[\d\s.,]{2,})",
                  r"(\d[\d\s.,]{2,})\s*(?:FCFA|fcfa|francs)?[^.\n]{0,15}?"
                  r"(charges?|co[ûu]ts?|d[ée]penses?|budget|investissement)"):
        for m in re.finditer(motif, t, flags=re.I):
            brut = next((g for g in m.groups() if g and _nombre(g) is not None), None)
            v = _nombre(brut) if brut else None
            if v and v >= 1000 and v not in vus:       # < 1000 F : bruit d'extraction
                vus.add(v)
                charges.append((v, m.group(0).strip()[:90]))
    # un prix unitaire n'est pas une charge : on retire les doublons de montant
    prix_connus = {c[1] for c in couples}
    charges = [c for c in charges if c[0] not in prix_connus]
    # Donnee douteuse (LAB 07 / LAB 08) : quantite + prix SANS devise -> on ne conclut pas.
    sans_devise = None
    if not couples:
        md = re.search(r"(\d[\d\s.,]*)\s*" + unite + r"\b[^\d\n]{0,25}?(\d[\d\s.,]{2,})"
                       r"(?!\s*(?:FCFA|fcfa|francs|F\b))", t, flags=re.I)
        sans_devise = md.group(0).strip()[:90] if md else None
    out = ["### Calculs de rentabilité (arithmétique faite par l'outil, pas par le modèle)",
           "#### Données extraites du texte"]
    if couples:
        out += ["| quantité | prix unitaire | recette calculée | extrait |", "|---|---|---|---|"]
        for q, p, u1, u2, ext in couples[:5]:
            out.append(f"| {q:g} {u1} | {p:g} FCFA/{u2} | **{q * p:,.0f} FCFA** | « {ext[:60]} » |")
    else:
        out = [f"{MARQUEUR_INSUFFISANT} calculer_marge — aucun couple quantite x prix exploitable "
               f"(devise manquante ou formulation differente)"] + out
        out += ["- Aucun couple quantité × prix exploitable trouvé."]
        if sans_devise:
            out += [f"- ⚠ **Prix sans devise** dans « {sans_devise} » : l'unité monétaire est "
                    "inconnue, donc **aucun calcul de recette n'est produit**. Demander la devise "
                    "et le prix unitaire avant toute conclusion (donnée douteuse, jamais corrigée "
                    "en silence)."]
    if charges:
        total = sum(c[0] for c in charges)
        out += ["", "#### Charges identifiées", "| montant | extrait |", "|---|---|"]
        out += [f"| {c[0]:,.0f} FCFA | « {c[1]} » |" for c in charges[:6]]
        out += ["", f"- **Total des charges identifiées : {total:,.0f} FCFA**"]
    else:
        total = None
        out += ["", "- Aucune charge chiffrée identifiée dans le texte."]

    out += ["", "#### Résultats (calculés)"]
    if couples and total is not None:
        recette = couples[0][0] * couples[0][1]
        marge = recette - total
        out += [f"- Recette : **{recette:,.0f} FCFA** − charges : **{total:,.0f} FCFA** "
                f"= marge brute : **{marge:,.0f} FCFA**"]
        out += [f"- Taux de marge sur recette : **{marge / recette * 100:.1f} %**"]
        if marge <= 0:
            out += ["- **Marge nulle ou négative : le projet tel que chiffré ne couvre pas ses charges.** "
                    "Ne pas engager de dépense avant de revoir prix, rendement ou charges."]
        else:
            pu = couples[0][1]
            qte = couples[0][0]
            out += [f"- **Seuil de rentabilité** : il faut vendre au moins **{total / pu:,.1f} "
                    f"{couples[0][2]}** au prix de {pu:g} FCFA pour couvrir {total:,.0f} FCFA de charges "
                    f"(soit {total / pu / qte * 100:.0f} % de la quantité annoncée).",
                    f"- Chaque unité vendue au-delà de {total / pu:,.1f} dégage {pu:g} FCFA en brut."]
    else:
        out += ["- **Calcul impossible en l'état** : il manque soit la recette (quantité × prix), "
                "soit les charges. Les demander au producteur plutôt que de supposer un chiffre."]
    out += ["", "- Hypothèses : les montants sont repris **tels qu'écrits dans la demande** ; "
                "aucune valeur de marché n'a été ajoutée. Vérifier les prix au marché et compter "
                "les pertes (mortalité, vols, avaries) avant de conclure à une marge réelle."]
    (dossier / "rentabilite.md").write_text("\n".join(out), encoding="utf-8")
    return "\n".join(out)


# --------------------------------------------------------------------------- relation producteur
def registre_producteur(demande: str, contexte: str, dossier: Path) -> str:
    """Ouvre/actualise un dossier producteur local à partir des informations fournies."""
    DATA.mkdir(exist_ok=True)
    (DATA / "producteurs").mkdir(exist_ok=True)
    t = f"{demande}\n{contexte}"
    nom = None
    m = re.search(r"(?:je m'appelle|mon nom est|nom\s*[:=])\s*([A-ZÉÈa-zéèêàïô'’\- ]{3,40})", t, flags=re.I)
    if m:
        nom = m.group(1).strip().title()
    tel = re.search(r"(\+?225[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{2}|\b0\d{9}\b|\b\d{2}\s?\d{2}\s?\d{2}\s?\d{2}\b)", t)
    lieu = extraire_localite(t)
    slug = sans_accents(nom or f"producteur-{time.strftime('%Y%m%d%H%M%S')}").replace(" ", "-")
    fichier = DATA / "producteurs" / f"{slug}.json"
    dossier_p = {}
    if fichier.exists():
        try:
            dossier_p = json.loads(fichier.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            dossier_p = {}
    dossier_p.update({"identifiant": slug,
                      "nom": nom or dossier_p.get("nom") or "non communiqué",
                      "telephone": (tel.group(1) if tel else dossier_p.get("telephone")) or "non communiqué",
                      "localite": (lieu.title() if lieu else dossier_p.get("localite")) or "non précisée",
                      "derniere_maj": time.strftime("%Y-%m-%dT%H:%M:%S")})
    historique = dossier_p.get("historique", [])
    historique.append({"date": time.strftime("%Y-%m-%d"), "demande": demande.strip()[:600]})
    dossier_p["historique"] = historique[-20:]
    fichier.write_text(json.dumps(dossier_p, ensure_ascii=False, indent=2), encoding="utf-8")

    champs = {"nom": dossier_p["nom"], "téléphone": dossier_p["telephone"],
              "localité": dossier_p["localite"], "superficie / effectif": None,
              "objectif (autoconsommation / vente)": None, "moyens (main-d'œuvre, budget)": None,
              "historique technique (campagnes passées)": None}
    manquants = [k for k, v in champs.items() if v is None]
    out = ["### Dossier producteur (registre local)", "", "| champ | valeur connue |", "|---|---|"]
    out += [f"| {k} | {v if v is not None else '**à recueillir**'} |" for k, v in champs.items()]
    out += ["", f"- Fichier du dossier : `{fichier}` ({len(historique)} échange(s) enregistré(s))",
            f"- Champs manquants pour qualifier correctement le dossier : "
            f"{', '.join(manquants) if manquants else 'aucun'}",
            "", "- Seules les informations **explicitement fournies** sont enregistrées : rien n'est "
                "déduit ni complété automatiquement. Données stockées localement sur ce poste, "
                "dans `data/producteurs/`."]
    (dossier / "dossier-producteur.md").write_text("\n".join(out), encoding="utf-8")
    return "\n".join(out)


# --------------------------------------------------------------------------- automatisation
MOIS = {m: i for i, m in enumerate(
    ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre",
     "octobre", "novembre", "decembre"], 1)}


def _dates_du_texte(t: str) -> list[tuple[date, str]]:
    """Repère les échéances exprimées dans le texte (absolues ou relatives)."""
    auj = date.today()
    trouve: list[tuple[date, str]] = []
    for m in re.finditer(r"(?:dans|sous|apres|après)\s+(\d{1,3})\s*(jours?|semaines?|mois)", t, flags=re.I):
        n, unite = int(m.group(1)), m.group(2).lower()
        d = auj + timedelta(days=n if "jour" in unite else 7 * n if "semaine" in unite else 30 * n)
        trouve.append((d, m.group(0)))
    for m in re.finditer(r"\bJ\s*\+\s*(\d{1,3})\b", t):
        trouve.append((auj + timedelta(days=int(m.group(1))), m.group(0)))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", t):
        j, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = a + 2000 if a < 100 else a
        try:
            trouve.append((date(a, mo, j), m.group(0)))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{1,2})\s+(" + "|".join(MOIS) + r")(?:\s+(\d{4}))?", sans_accents(t)):
        d = int(m.group(1)); mo = MOIS[m.group(2)]; a = int(m.group(3)) if m.group(3) else auj.year
        try:
            cand = date(a, mo, d)
            trouve.append((cand if cand >= auj else date(a + 1, mo, d), m.group(0)))
        except ValueError:
            pass
    for m in re.finditer(r"(semaine prochaine|mois prochain|la semaine prochaine|le mois prochain)", sans_accents(t)):
        trouve.append((auj + timedelta(days=7 if "semaine" in m.group(1) else 30), m.group(1)))
    vus, uniques = set(), []
    for d, ext in sorted(trouve):
        if d in vus:
            continue
        vus.add(d)
        phrase = next((p.strip() for p in re.split(r"[.\n;]", t) if ext in sans_accents(p)), ext)
        uniques.append((d, phrase[:140]))
    return uniques


def calendrier_et_rappels(demande: str, contexte: str, dossier: Path) -> str:
    """Génère calendrier .ics + file de rappels + script de vérification à partir des échéances citées."""
    evts = _dates_du_texte(f"{demande}\n{contexte}")
    (DATA / "automatisations").mkdir(parents=True, exist_ok=True)
    ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AGROGUIDCI//FR", "CALSCALE:GREGORIAN"]
    rappels = []
    for i, (d, libelle) in enumerate(evts, 1):
        uid = f"agroguidci-{d.isoformat()}-{i}@local"
        ics += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}",
                f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                f"SUMMARY:AGROGUIDCI - {libelle[:70]}",
                f"DESCRIPTION:{libelle[:200]}", "END:VEVENT"]
        rappels.append({"echeance": d.isoformat(), "libelle": libelle, "cree_le": time.strftime("%Y-%m-%d")})
    ics.append("END:VCALENDAR")
    chemin_ics = dossier / "calendrier.ics"
    chemin_ics.write_text("\r\n".join(ics), encoding="utf-8")
    chemin_rappels = DATA / "automatisations" / "rappels.json"
    existants = []
    if chemin_rappels.exists():
        try:
            existants = json.loads(chemin_rappels.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            existants = []
    chemin_rappels.write_text(json.dumps(existants + rappels, ensure_ascii=False, indent=2), encoding="utf-8")

    out = ["### Automatisations produites", "",
           f"- Calendrier importable (Outlook, Google Agenda, téléphone) : `{chemin_ics}`",
           f"- File de rappels locale : `{chemin_rappels}` ({len(existants) + len(rappels)} rappel(s) au total)"]
    if rappels:
        out += ["", "| échéance | opération |", "|---|---|"]
        out += [f"| {r['echeance']} | {r['libelle'][:90]} |" for r in rappels]
    else:
        out += ["", "- **Aucune échéance datée dans la demande** : rien n'a été planifié. Un rappel "
                    "suppose une date — la demander (ex. « dans 3 semaines », « le 15/11/2026 »)."]
    out += ["", "#### Pour aller au bout (commandes exactes, non exécutées ici)",
            "```",
            f"REMINDER_FILE={chemin_rappels}",
            "python verifier_rappels.py            # liste les rappels échus / à venir",
            "```",
            "- L'activation automatique (tâche planifiée Windows) est décrite dans "
            "`verifier_rappels.py` ; elle n'est **pas** installée tant qu'elle n'est pas explicitement "
            "demandée — et toute activation est vérifiée après coup."]
    (dossier / "automatisations.md").write_text("\n".join(out), encoding="utf-8")
    return "\n".join(out)


def activer_rappels(demande: str, contexte: str, dossier: Path) -> str:
    """ACTION SENSIBLE : n'execute rien elle-meme — depose une demande de validation humaine."""
    # On n'analyse QUE la demande d'origine : le contexte de l'agent principal peut
    # contenir des mots (« programme », « planifie ») qui declencheraient a tort
    # l'installation d'une tache sur le poste.
    origine = demande.split("\n\nCONTEXTE CLARIFIE PAR LE COORDONNATEUR\n")[0]
    t = sans_accents(origine)
    script = ROOT / "verifier_rappels.py"
    out = ["### Verification des rappels — action sensible (validation humaine requise)"]
    nom_tache = "AGROGUIDCI_Rappels"
    commande = f'"{sys.executable}" "{script}"'
    out += ["", f"- Tâche Windows visée : `{nom_tache}` (quotidienne, 07:00) → `{commande}`"]
    if not re.search(r"\b(active|activer|planifie|planifier|programme|programmer|mets en place|"
                     r"mettre en place|cree la tache|créer la tâche|automatise)\b", t):
        out += ["", "- **Ni activée, ni déposée en validation** : la demande ne demande pas "
                    "explicitement la mise en place. Commande prête à exécuter (ou à faire passer "
                    "par `validation.py` si on veut l'encadrer) :",
                "```", f'schtasks /Create /SC DAILY /ST 07:00 /TN {nom_tache} /TR {commande} /F', "```"]
        return "\n".join(out)
    if not script.exists():
        out += ["", f"- **Échec** : `{script}` absent — aucune demande ni tâche."]
        return "\n".join(out)
    import validation          # import paresseux : evite le cycle outils <-> validation
    dem = validation.demander(
        action="activer_rappels",
        agent="AGROGUIDCI Sous-agent Automatisation",
        motif=(f"Installer la tache planifiee Windows « {nom_tache} » (quotidienne 07:00) qui "
               f"verifie les rappels du producteur. Action soumise a validation humaine : elle "
               f"modifie le poste."),
        params={"source": origine[:600], "rappels": str(DATA / "automatisations" / "rappels.json"),
                "dossier": str(dossier)})
    out += ["", f"- **Demande de validation humaine enregistree** : id `{dem['id']}`",
            f"- Deposee dans `{dem['chemin']}` — l'action n'a **pas** ete executee.",
            "", "- Approbation par un operateur :", "```",
            f"python validation.py --approuver {dem['id']}", "```",
            "- Refus motive :", "```",
            f'python validation.py --refuser {dem["id"]} --motif "raison"', "```",
            "", "- Apres approbation, l'execution (creation puis relecture de la tache) est faite "
                "par `validation.py` et la preuve reelle est archivee dans le dossier de la run."]
    (dossier / "demande-validation.md").write_text("\n".join(out), encoding="utf-8")
    return "\n".join(out)


def activer_rappels_executer(params: dict) -> dict:
    """Execution REELLE de l'action sensible : appelee uniquement par validation.py,
    apres approbation humaine. Elle cree la tache puis la relit (preuve)."""
    nom_tache = "AGROGUIDCI_Rappels"
    script = ROOT / "verifier_rappels.py"
    commande = f'"{sys.executable}" "{script}"'
    lignes = ["### Execution de l'action sensible approuvee", f"- tache visee : `{nom_tache}`",
              f"- commande : `{commande}`",
              f"- demande d'origine : {(params.get('source') or '')[:200]}"]
    if not script.exists():
        lignes += ["", f"- **Echec** : script absent ({script}) — rien n'a ete cree."]
        return {"ok": False, "sortie": "\n".join(lignes)}
    try:
        creer = subprocess.run(["schtasks", "/Create", "/SC", "DAILY", "/ST", "07:00", "/TN", nom_tache,
                                "/TR", commande, "/F"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        lignes += ["", f"- **Echec de creation** : {e}"]
        return {"ok": False, "sortie": "\n".join(lignes)}
    lignes += ["", "#### Creation", f"- code de sortie : {creer.returncode}",
               f"- sortie : `{(creer.stdout or creer.stderr or '').strip()[:300]}`"]
    verif = subprocess.run(["schtasks", "/Query", "/TN", nom_tache, "/FO", "LIST"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    lignes += ["", "#### Verification (relecture reelle de la tache)", "```",
               (verif.stdout or verif.stderr or "").strip()[:700], "```"]
    ok = verif.returncode == 0 and creer.returncode == 0
    lignes += ["", f"- Conclusion : tache **{'installee et verifiee' if ok else 'NON verifiee'}** "
                   f"(creation {creer.returncode}, relecture {verif.returncode}).",
               "```", f"schtasks /Delete /TN {nom_tache} /F     # desactivation", "```"]
    dossier = Path(params.get("dossier") or (ROOT / "out"))
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "automatisation-activee.md").write_text("\n".join(lignes), encoding="utf-8")
    except OSError:
        pass
    return {"ok": ok, "sortie": "\n".join(lignes)}


# --------------------------------------------------------------------------- registre
OUTILS = {
    "meteo_et_pluies": meteo_et_pluies,
    "contexte_documentaire": contexte_documentaire,
    "analyser_tableau": analyser_tableau,
    "calculer_marge": calculer_marge,
    "registre_producteur": registre_producteur,
    "calendrier_et_rappels": calendrier_et_rappels,
    "activer_rappels": activer_rappels,
}


def executer_outil(nom: str, demande: str, contexte: str, dossier: Path) -> str:
    f = OUTILS.get(nom)
    if not f:
        return f"### Outil « {nom} » inconnu — aucune donnée produite."
    try:
        return f(demande, contexte, dossier)
    except Exception as e:      # un outil qui casse ne doit jamais faire inventer une donnee
        return (f"{MARQUEUR_ECHEC} {nom} — {type(e).__name__}: {e}\n"
                f"### Outil « {nom} » — ECHEC TECHNIQUE\n{type(e).__name__}: {e}\n"
                "Aucune donnée n'a été produite par cet outil : ne rien affirmer sur son domaine.")


if __name__ == "__main__":
    d = ROOT / "out" / "outils-test"
    d.mkdir(parents=True, exist_ok=True)
    print(executer_outil("meteo_et_pluies", "2 ha a Bouake", "", d)[:600])
    print()
    print(executer_outil("calculer_marge",
                         "800 kg de mais a 250 FCFA le kg, charges 180000 FCFA", "", d)[:800])

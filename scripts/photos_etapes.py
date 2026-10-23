"""photos_etapes.py — trouve des photos réelles (Wikimedia Commons) pour deux étapes
clés de chaque fiche : la plantation/le semis, et la récolte.

    python scripts/photos_etapes.py --chercher      # cherche + télécharge les candidats
    python scripts/photos_etapes.py --planche       # fabrique la planche de contrôle
    python scripts/photos_etapes.py --installer     # copie les choix retenus + crédits

Aucune image n'est publiée sans contrôle visuel : la planche de contrôle montre les
candidats numérotés, et la sélection se fait dans SELECTION ci-dessous.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "web" / "assets" / "cultures"
TMP = ROOT / "out" / "photos-candidats"
CREDITS = DEST / "_sources.json"
API = "https://commons.wikimedia.org/w/api.php"
UA = ("AGROGUIDCI/1.0 (site de conseil agricole; contact aicmaxter@gmail.com) "
      "Python-urllib/3")

# (culture, rôle) -> requête Commons
REQUETES: dict[tuple[str, str], str] = {
    ("voandzou", "plantation"): "Vigna subterranea field crop",
    ("voandzou", "recolte"): "Bambara groundnut harvest",
    ("fonio", "plantation"): "fonio field growing",
    ("fonio", "recolte"): "fonio harvest threshing",
    ("sesame", "plantation"): "Sesamum indicum field",
    ("sesame", "recolte"): "sesame harvest bundles",
    ("patatedouce", "plantation"): "Ipomoea batatas field crop",
    ("patatedouce", "recolte"): "sweet potato harvest field",
    ("soja", "plantation"): "Glycine max field crop",
    ("soja", "recolte"): "soybean pods harvest",
    ("igname", "plantation"): "yam mounds Ghana",
    ("igname", "recolte"): "yam tubers market Ghana",
    ("plantain", "plantation"): "plantain plantation Ghana",
    ("plantain", "recolte"): "plantain bunch harvest",
    ("poivre", "plantation"): "Piper nigrum plantation",
    ("poivre", "recolte"): "Piper nigrum berries",
    ("gingembre", "plantation"): "Zingiber officinale field",
    ("gingembre", "recolte"): "Zingiber officinale rhizome",
    ("curcuma", "plantation"): "Curcuma longa field",
    ("curcuma", "recolte"): "turmeric harvest rhizomes",
    ("piment", "plantation"): "Capsicum field Ghana",
    ("piment", "recolte"): "chili peppers drying",
}

# Titres à écarter d'office : objets de musée, planches anciennes, alcools, cartes…
BAD = ("illustration", "flora", "moth", "butterfly", "lily", "wild ginger",
       "botanic", "garden", "market", "museum", "musée", "wellcome", "herbier", "herbarium", "botanical illustration",
       "drawing", "engraving", "lithograph", "poster", "label", "stamp", "coin",
       "alcohol", "beer", "wine", "spirit", "map ", "diagram", "cross section",
       "powder", "oil bottle", "ketchup", "sauce", "spice jar", "market price")


def http_json(url: str, essais: int = 3) -> dict:
    for i in range(essais):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                    # réseau capricieux : on réessaie
            if i == essais - 1:
                print("   ! échec API :", type(e).__name__)
                return {}
            time.sleep(1.5 * (i + 1))
    return {}


def candidats(requete: str, limite: int = 10) -> list[dict]:
    params = urllib.parse.urlencode({
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:bitmap {requete}", "gsrnamespace": 6,
        "gsrlimit": limite, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1000, "format": "json",
    })
    data = http_json(f"{API}?{params}")
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        titre = p.get("title") or ""
        if info.get("mime") != "image/jpeg":
            continue
        largeur, hauteur = info.get("width") or 0, info.get("height") or 0
        if largeur < 800 or hauteur == 0:
            continue
        if any(b in titre.lower() for b in BAD):
            continue
        out.append({
            "titre": titre,
            "url": info.get("thumburl") or info.get("url"),
            "largeur": largeur, "hauteur": hauteur,
            "portrait": hauteur > largeur * 1.05,
            "auteur": re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value") or "").strip()[:120],
            "licence": (meta.get("LicenseShortName") or {}).get("value") or "",
            "page": info.get("descriptionurl") or "",
        })
    return out


def telecharger(url: str, chemin: Path, essais: int = 3) -> bool:
    for i in range(essais):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "image/*",
                "Referer": "https://commons.wikimedia.org/"})
            with urllib.request.urlopen(req, timeout=45) as r:
                chemin.write_bytes(r.read())
            return chemin.stat().st_size > 20000
        except Exception:
            if i == essais - 1:
                return False
            time.sleep(1.5 * (i + 1))
    return False


def chercher() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    index = {}
    for (cid, role), requete in REQUETES.items():
        print(f"· {cid}/{role} : {requete!r}")
        pour = []
        for c in candidats(requete):
            nom = f"{cid}-{role}-{len(pour)}.jpg"
            if telecharger(c["url"], TMP / nom):
                c["fichier"] = nom
                pour.append(c)
                print(f"    + {c['titre'][:70]}  ({c['largeur']}x{c['hauteur']})")
            if len(pour) >= 6:
                break
        index[f"{cid}/{role}"] = pour
        time.sleep(0.4)
    (TMP / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    print("candidats :", sum(len(v) for v in index.values()))


def planche() -> None:
    from PIL import Image, ImageDraw
    index = json.loads((TMP / "index.json").read_text(encoding="utf-8"))
    tuiles = []
    for cle, cands in index.items():
        for c in cands:
            tuiles.append((f"{cle} {c['fichier'].split('-')[-1].replace('.jpg', '')}", c["fichier"]))
    if not tuiles:
        print("aucun candidat")
        return
    cols, larg, haut = 6, 260, 200
    lignes = (len(tuiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * larg, lignes * (haut + 18)), "white")
    d = ImageDraw.Draw(sheet)
    for i, (label, fichier) in enumerate(tuiles):
        x, y = (i % cols) * larg, (i // cols) * (haut + 18)
        try:
            im = Image.open(TMP / fichier).convert("RGB")
        except Exception:
            continue
        im.thumbnail((larg - 6, haut - 6))
        sheet.paste(im, (x + 3, y + 3))
        d.text((x + 4, y + haut + 2), label[:44], fill="black")
    sortie = ROOT / "out" / "planche-photos.jpg"
    sheet.save(sortie, quality=82)
    print("planche :", sortie)


def installer() -> None:
    """Copie les fichiers retenus (SELECTION) et met à jour les crédits."""
    index = json.loads((TMP / "index.json").read_text(encoding="utf-8"))
    credits = json.loads(CREDITS.read_text(encoding="utf-8"))
    faits = 0
    for cle, choix in SELECTION.items():
        cid, role = cle.split("/")
        cands = index.get(cle) or []
        if choix >= len(cands):
            print("  ! choix hors liste :", cle, choix)
            continue
        c = cands[choix]
        cible = DEST / f"{cid}-{role}.jpg"
        from PIL import Image
        im = Image.open(TMP / c["fichier"]).convert("RGB")
        im.thumbnail((1000, 1000), Image.LANCZOS)
        im.save(cible, "JPEG", quality=82, optimize=True, progressive=True)
        credits.setdefault(cid, {})["etapes"] = credits.get(cid, {}).get("etapes") or {}
        credits[cid]["etapes"][role] = {
            "fichier": f"assets/cultures/{cid}-{role}.jpg",
            "titre": c["titre"], "auteur": c["auteur"], "licence": c["licence"],
            "page": c["page"],
        }
        faits += 1
        print(f"  installé {cible.name} ({cible.stat().st_size // 1024} ko) — {c['titre'][:60]}")
    CREDITS.write_text(json.dumps(credits, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    print("photos installées :", faits)


# Sélection issue du contrôle visuel de la planche (index du candidat par étape).
SELECTION: dict[str, int] = {
    "voandzou/recolte": 0,
    "fonio/recolte": 0,
    "sesame/plantation": 1,
    "patatedouce/recolte": 4,
    "soja/plantation": 5,
    "soja/recolte": 2,
    "igname/plantation": 0,
    "igname/recolte": 1,
    "plantain/plantation": 0,
    "plantain/recolte": 3,
    "poivre/plantation": 2,
    "poivre/recolte": 2,
    "gingembre/plantation": 0,
    "gingembre/recolte": 2,
    "curcuma/plantation": 0,
    "curcuma/recolte": 3,
    "piment/recolte": 3,
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chercher", action="store_true")
    ap.add_argument("--planche", action="store_true")
    ap.add_argument("--installer", action="store_true")
    a = ap.parse_args()
    if a.chercher:
        chercher()
    if a.planche:
        planche()
    if a.installer:
        installer()
    if not any((a.chercher, a.planche, a.installer)):
        print(__doc__)

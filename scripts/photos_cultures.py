"""photos_cultures.py — récupère une photo réelle (Wikimedia Commons) par culture.

    python scripts/photos_cultures.py --chercher          # liste les candidats
    python scripts/photos_cultures.py --installer         # télécharge le choix retenu

Le script n'invente aucun crédit : l'auteur, la licence et la page sont lus dans
l'API Commons (extmetadata) et écrits dans web/assets/cultures/_sources.json.
Une culture sans photo libre vérifiée n'est pas publiée avec une image.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "web" / "assets" / "cultures"
CREDITS = DEST / "_sources.json"
API = "https://commons.wikimedia.org/w/api.php"
UA = "AGROGUIDCI/1.0 (vitrine agricole; contact aicmaxter@gmail.com)"

RECHERCHES = {
    "tomate": "tomato field harvest red fruits Africa",
    "oignon": "onion bulbs market harvest Africa",
    "gombo": "Abelmoschus esculentus okra fruits plant",
    "aubergine": "Solanum aethiopicum african eggplant fruit",
    "chou": "cabbage head field harvest Brassica",
    "pasteque": "watermelon Citrullus lanatus fruit farm harvest",
    "papaye": "Carica papaya papaya fruits tree",
    "ananas": "Ananas comosus pineapple fruit plant",
    "manguier": "Mangifera indica mango fruits tree",
}

LICENCES_OK = re.compile(r"(cc[ -]?by|cc0|public domain|domaine public)", re.I)


def _reessayer(fn, tentatives=4, pause=3.0):
    """Wikimedia réinitialise parfois la connexion : on retente avec un délai croissant."""
    import time
    derniere = None
    for i in range(tentatives):
        try:
            return fn()
        except Exception as exc:  # réseau, TLS, coupure
            derniere = exc
            if i == tentatives - 1:
                raise
            time.sleep(pause * (i + 1))
    raise derniere


def api(params: dict) -> dict:
    params = dict(params, format="json")
    url = API + "?" + urllib.parse.urlencode(params)

    def appel():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode("utf-8"))

    return _reessayer(appel)


def candidats(terme: str, limite: int = 6) -> list[dict]:
    d = api({
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:bitmap {terme}", "gsrnamespace": "6", "gsrlimit": str(limite),
        "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": "1280",
    })
    out = []
    for page in (d.get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        get = lambda k: re.sub(r"<[^>]+>", "", (meta.get(k) or {}).get("value", "") or "").strip()
        licence = get("LicenseShortName")
        if not licence or not LICENCES_OK.search(licence):
            continue
        if int(info.get("width") or 0) < 900:
            continue
        out.append({
            "titre": page.get("title", "").replace("File:", ""),
            "auteur": get("Artist") or "auteur non précisé",
            "licence": licence,
            "page": info.get("descriptionurl") or "",
            "url": info.get("thumburl") or info.get("url") or "",
            "largeur": info.get("width"),
        })
    return out


def telecharger(url: str, dest: Path) -> int:
    def descente():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    data = _reessayer(descente)
    dest.write_bytes(data)
    return len(data)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--chercher", action="store_true")
    p.add_argument("--installer", action="store_true")
    a = p.parse_args()

    credits = json.loads(CREDITS.read_text(encoding="utf-8")) if CREDITS.exists() else {}

    if a.chercher or not a.installer:
        for cid, terme in RECHERCHES.items():
            print(f"\n== {cid} ==")
            for c in candidats(terme, 4):
                print(f"   {c['titre'][:70]} | {c['licence']} | {c['auteur'][:30]} | {c['largeur']}px")
        return 0

    # installer : première photo libre de chaque recherche, sauf choix déjà enregistré
    ecrits = 0
    for cid, terme in RECHERCHES.items():
        dest = DEST / f"{cid}.jpg"
        if dest.exists() and credits.get(cid, {}).get("choix"):
            print(f"- {cid} : déjà installé")
            continue
        liste = candidats(terme, 6)
        if not liste:
            print(f"! {cid} : aucune photo libre trouvée")
            continue
        choix = liste[0]
        taille = telecharger(choix["url"], dest)
        credits[cid] = {"auteur": choix["auteur"], "licence": choix["licence"],
                        "page": choix["page"], "fichier": f"assets/cultures/{cid}.jpg",
                        "choix": choix["titre"]}
        ecrits += 1
        print(f"+ {cid} : {choix['titre'][:60]} ({taille // 1024} Ko, {choix['licence']})")
    CREDITS.write_text(json.dumps(credits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{ecrits} photo(s) installée(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

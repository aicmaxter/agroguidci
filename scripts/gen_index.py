"""gen_index.py — régénère les fiches cultures/épices de la vitrine depuis les données.

Source de vérité :
    web/assets/cultures.json      (contenu des fiches : nom, cycle, atouts, débouché…)
    web/assets/cultures/_sources.json  (auteur + licence + page de chaque photo)

Sortie :
    web/index.html, entre les marqueurs <!-- FICHES:DEBUT --> et <!-- FICHES:FIN -->,
    plus les compteurs des filtres et de l'onglet.

    python scripts/gen_index.py            # écrit
    python scripts/gen_index.py --verifier # contrôle seulement, code 1 si écart
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "web" / "index.html"
DONNEES = ROOT / "web" / "assets" / "cultures.json"
PHOTOS = ROOT / "web" / "assets" / "cultures" / "_sources.json"
DEBUT, FIN = "<!-- FICHES:DEBUT -->", "<!-- FICHES:FIN -->"


def e(t: str) -> str:
    return html.escape(str(t or ""), quote=True)


def carte(c: dict, photo: dict | None) -> str:
    classes = "crop reveal" + (" epice" if c.get("epice") else "")
    badge = "crop-badge" + (" epice" if c.get("epice") else "") + (" nou" if c.get("nouveau") else "")
    credit = ""
    if photo:
        credit = ('<p class="crop-credit">Photo : ' + e(photo["auteur"]) + " · " + e(photo["licence"]) +
                  ' · <a href="' + e(photo["page"]) + '" target="_blank" rel="noreferrer">Wikimedia</a></p>')
    source = ""
    if c.get("source"):
        lien = c.get("source_url") or "#"
        source = ('<p class="crop-source">Pourquoi maintenant : ' + e(c["source"]) +
                  ' — <a href="' + e(lien) + '" target="_blank" rel="noreferrer">source</a></p>')

    # Dérivés WebP (scripts/optimiser_photos.py) : la carte ne télécharge plus
    # l'original de 1200 px, mais 480 px (~40 Ko). Repli JPEG si le dérivé manque.
    jpg = f"assets/cultures/{e(c['id'])}.jpg"
    petit, grand = f"assets/cultures/480/{e(c['id'])}.webp", f"assets/cultures/960/{e(c['id'])}.webp"
    webp_ok = (ROOT / "web" / petit).exists() and (ROOT / "web" / grand).exists()
    if webp_ok:
        image = (
            '<picture>'
            f'<source type="image/webp" srcset="{petit} 480w, {grand} 960w" '
            'sizes="(max-width: 560px) 92vw, (max-width: 760px) 46vw, (max-width: 1180px) 31vw, 280px">'
            f'<img src="{jpg}" alt="{e(c["nom"])} — photographie réelle" '
            'width="1200" height="750" loading="lazy" decoding="async">'
            '</picture>'
        )
    else:
        image = (f'<img src="{jpg}" alt="{e(c["nom"])} — photographie réelle" '
                 'width="1200" height="750" loading="lazy" decoding="async">')

    return f'''          <article class="{classes}" data-type="{e(c['type'])}" data-nom="{e(c['nom'].lower())}">
            <figure class="crop-img">
              <a class="crop-lien-img" href="cultures/{e(c['id'])}" aria-label="Lire la fiche {e(c['nom'])}">
                {image}
              </a>
              <span class="{badge}">{e(c['badge'])}</span>
            </figure>
            <div class="crop-body">
              <h3><a class="crop-lien-titre" href="cultures/{e(c['id'])}">{e(c["nom"])}</a></h3>
              <p class="surnom">{e(c['surnom'])}</p>
              <p class="desc">{e(c['desc'])}</p>
              <dl>
                <dt>Cycle</dt><dd>{e(c['cycle'])}</dd>
                <dt>Atouts</dt><dd>{e(c['atouts'])}</dd>
                <dt>Débouché</dt><dd>{e(c['debouche'])}</dd>
              </dl>
              <p class="crop-plus"><a href="cultures/{e(c['id'])}">Fiche complète : climat, itinéraire, récolte, budget →</a></p>
              {source}
              {credit}
            </div>
          </article>'''


def construire() -> tuple[str, int, int, int]:
    donnees = json.loads(DONNEES.read_text(encoding="utf-8"))
    photos = json.loads(PHOTOS.read_text(encoding="utf-8")) if PHOTOS.exists() else {}
    cultures = donnees["cultures"]
    cartes = "\n".join(carte(c, photos.get(c["id"])) for c in cultures)
    vivrieres = sum(1 for c in cultures if c["type"] == "vivriere")
    epices = sum(1 for c in cultures if c["type"] == "epice")
    return cartes, len(cultures), vivrieres, epices


def main() -> int:
    p = argparse.ArgumentParser(description="Régénère les fiches cultures de web/index.html")
    p.add_argument("--verifier", action="store_true", help="ne rien écrire, signaler un écart")
    a = p.parse_args()

    cartes, total, vivrieres, epices = construire()
    page = INDEX.read_text(encoding="utf-8")
    if DEBUT not in page or FIN not in page:
        print(f"ERREUR : marqueurs absents de {INDEX}")
        return 2

    avant = page.split(DEBUT)[1].split(FIN)[0]
    nouvelle = page.split(DEBUT)[0] + DEBUT + "\n" + cartes + "\n" + FIN + page.split(FIN, 1)[1]

    # compteurs des filtres et de l'onglet
    nouvelle = re.sub(r'(<button class="filtre[^"]*" type="button" data-filtre="tous">Toutes\s*<span>)\d+(</span>)',
                      rf"\g<1>{total}\g<2>", nouvelle)
    nouvelle = re.sub(r'(data-filtre="vivriere">Vivrières\s*<span>)\d+(</span>)', rf"\g<1>{vivrieres}\g<2>", nouvelle)
    nouvelle = re.sub(r'(data-filtre="epice">Épices\s*<span>)\d+(</span>)', rf"\g<1>{epices}\g<2>", nouvelle)
    nouvelle = re.sub(r'(<span class="tab-count">)\d+(</span>)', rf"\g<1>{total}\g<2>", nouvelle)

    ecart = avant.strip() != cartes.strip()
    print(f"fiches : {total} (vivrières {vivrieres}, épices {epices}) · écart avec index.html : {'oui' if ecart else 'non'}")
    if a.verifier:
        return 1 if ecart else 0
    INDEX.write_text(nouvelle, encoding="utf-8")
    print(f"{INDEX} régénéré ({len(nouvelle)} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

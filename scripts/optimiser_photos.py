"""optimiser_photos.py — dérivés WebP des photos de cultures.

Les originaux (1200×750, 120–320 Ko) restent la source de vérité. Ce script écrit
deux dérivés légers, utilisés par les cartes de l'accueil et les fiches :

    web/assets/cultures/480/<nom>.webp    (480 px de large, ~25–40 Ko)
    web/assets/cultures/960/<nom>.webp    (960 px de large, ~70–110 Ko)

    python scripts/optimiser_photos.py            # écrit / met à jour
    python scripts/optimiser_photos.py --verifier # code 1 si un dérivé manque

Aucune photo n'est supprimée ; si Pillow est absent, le script le dit et sort en 2.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PHOTOS = RACINE / "web" / "assets" / "cultures"
LARGEURS = (480, 960)
QUALITE = 80


def main() -> int:
    p = argparse.ArgumentParser(description="Génère les dérivés WebP des photos de cultures")
    p.add_argument("--verifier", action="store_true", help="ne rien écrire, signaler les manquants")
    a = p.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("Pillow absent : installation impossible des dérivés WebP.")
        return 2

    sources = sorted(
        f for f in PHOTOS.glob("*.jpg")
        if f.is_file()
    )
    if not sources:
        print(f"Aucune photo dans {PHOTOS}")
        return 2

    manquants: list[str] = []
    ecrits = 0
    avant = apres = 0

    for src in sources:
        avant += src.stat().st_size
        for largeur in LARGEURS:
            dossier = PHOTOS / str(largeur)
            dossier.mkdir(exist_ok=True)
            sortie = dossier / (src.stem + ".webp")
            if a.verifier:
                if not sortie.exists():
                    manquants.append(str(sortie.relative_to(RACINE)))
                elif sortie.exists():
                    apres += sortie.stat().st_size
                continue
            with Image.open(src) as im:
                im = im.convert("RGB")
                if im.width > largeur:
                    hauteur = round(im.height * largeur / im.width)
                    reech = getattr(Image, "Resampling", Image).LANCZOS
                    im = im.resize((largeur, hauteur), reech)
                im.save(sortie, "WEBP", quality=QUALITE, method=6)
            ecrits += 1
            apres += sortie.stat().st_size

    if a.verifier:
        if manquants:
            print(f"{len(manquants)} dérivé(s) manquant(s) :")
            for m in manquants[:12]:
                print("  -", m)
            return 1
        print(f"dérivés à jour : {len(sources)} photos × {len(LARGEURS)} largeurs")
        return 0

    print(
        f"{ecrits} fichier(s) WebP écrit(s) · originaux {avant / 1e6:.1f} Mo "
        f"→ dérivés {apres / 1e6:.1f} Mo"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

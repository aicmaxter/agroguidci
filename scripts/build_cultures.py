"""build_cultures.py — génère les fiches détaillées depuis content/cultures-*.json.

    python scripts/build_cultures.py            # écrit web/cultures/<id>.html
    python scripts/build_cultures.py --verifier # échoue si une page a divergé

Principes :
    - une seule source de contenu (les fichiers JSON de content/) ;
    - aucune donnée n'est inventée : les limites et le niveau de confiance sont publiés ;
    - les sections vides sont omises, jamais remplies par du texte générique.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENU = ROOT / "content"
SORTIE = ROOT / "web" / "cultures"

TITRES = [
    ("presentation", "Présentation et utilisations"),
    ("conditions", "Climat et sols"),
    ("varietes", "Variétés adaptées"),
    ("calendrier", "Calendrier cultural"),
    ("preparation", "Préparation du terrain"),
    ("semis", "Semis et plantation"),
    ("entretien", "Entretien, fertilisation, irrigation"),
    ("sante", "Maladies, ravageurs et prévention"),
    ("recolte", "Récolte et post-récolte"),
    ("conservation", "Conservation et transformation"),
    ("economie", "Coûts, rendements et débouchés"),
]

GABARIT = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{nom} — fiche technique | AGROGUIDCI</title>
  <meta name="description" content="{description}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Manrope:wght@400;500;600;700;800&display=swap">
  <link rel="stylesheet" href="../assets/site.css?v=10">
  <link rel="stylesheet" href="../assets/fiche.css?v=1">
</head>
<body class="fiche-page">
<a class="skip" href="#fiche">Aller au contenu</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="../" aria-label="AGROGUIDCI, accueil">
      <span class="brand-mark" aria-hidden="true">🌱</span>
      <span class="brand-text">AGROGUIDCI</span>
    </a>
    <nav class="nav" aria-label="Navigation principale">
      <a class="navlink" href="../#cultures">Cultures</a>
      <a class="navlink" href="../#prix">Prix du kilo</a>
      <a class="navlink" href="../#actus">Actualités</a>
      <a class="navlink" href="../confidentialite.html">Confidentialité</a>
    </nav>
    <a class="btn btn-primary header-cta" href="../#conseil">Conseil gratuit</a>
  </div>
</header>

<main id="fiche" class="fiche-detail">
  <div class="wrap">
    <p class="fil-ariane"><a href="../#cultures">← Toutes les cultures</a></p>

    <header class="fiche-entete">
      <div class="fiche-texte">
        <p class="eyebrow">{famille}</p>
        <h1>{nom}</h1>
        <p class="fiche-surnom">{surnom}</p>
        <ul class="fiche-reperes">
          <li><strong>Cycle</strong> {cycle}</li>
          <li><strong>Mise à jour</strong> {maj}</li>
          <li><strong>Niveau de confiance</strong> <span class="confiance {classe_confiance}">{confiance}</span></li>
        </ul>
      </div>
      <figure class="fiche-photo">
        <img src="../assets/cultures/{id}.jpg" alt="{nom} — photographie réelle" width="1200" height="750">
        <figcaption>{credit}</figcaption>
      </figure>
    </header>

    <nav class="fiche-sommaire" aria-label="Sommaire de la fiche">
      <ol>{sommaire}</ol>
    </nav>

    {sections}

    <section class="fiche-section" id="tutoriel">
      <h2>Tutoriel étape par étape</h2>
      <ol class="tutoriel">{tutoriel}</ol>
    </section>

    <section class="fiche-section" id="sources">
      <h2>Sources, vérification et limites</h2>
      <ul class="sources-liste">{sources}</ul>
      <p class="limites"><strong>Limites de cette fiche.</strong> {limites}</p>
      <p class="maj">Dernière mise à jour : {maj}. Les prix, rendements et calendriers locaux ne sont mentionnés que lorsqu'ils sont documentés ; dans le doute, la fiche le dit.</p>
    </section>

    <section class="fiche-actions" aria-label="Actions">
      <button class="btn btn-primary btn-lg" type="button" data-chat="ouvrir" data-culture="{id}">Poser une question sur cette culture</button>
      <a class="btn btn-ghost btn-lg" href="../#prix">Voir les prix au kilo</a>
    </section>
  </div>
</main>

<footer class="site-footer">
  <div class="wrap">
    <p>AGROGUIDCI — conseil agricole pour la Côte d'Ivoire. <a href="../confidentialite.html">Politique de confidentialité</a></p>
  </div>
</footer>
<script src="../assets/chat.js?v=12" defer></script>
</body>
</html>
"""


def e(t: object) -> str:
    return html.escape(str(t or ""), quote=True)


def charger() -> tuple[dict, dict]:
    cultures: dict[str, dict] = {}
    meta: dict = {}
    for f in sorted(CONTENU.glob("cultures-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        meta.update({k: v for k, v in d.items() if k.startswith("_")})
        cultures.update(d.get("cultures") or {})
    return cultures, meta


def ancres(cultures: dict) -> dict:
    return {}


def page(cid: str, c: dict, photos: dict, maj: str) -> str:
    sommaire, sections = [], []
    for cle, titre in TITRES:
        texte = (c.get(cle) or "").strip()
        if not texte:
            continue
        sommaire.append(f'<li><a href="#{cle}">{e(titre)}</a></li>')
        sections.append(f'''    <section class="fiche-section" id="{cle}">
      <h2>{e(titre)}</h2>
      <p>{e(texte)}</p>
    </section>''')
    sommaire.append('<li><a href="#tutoriel">Tutoriel étape par étape</a></li>')
    sommaire.append('<li><a href="#sources">Sources et limites</a></li>')

    tutoriel = "\n".join(
        f'<li><strong>{e(etape.get("titre"))}</strong><p>{e(etape.get("texte"))}</p></li>'
        for etape in (c.get("tutoriel") or []))

    sources = []
    for s in (c.get("sources") or []):
        libelle = " · ".join(x for x in (s.get("organisme"), s.get("titre")) if x)
        lien = f' — <a href="{e(s["url"])}" target="_blank" rel="noreferrer">consulter</a>' if s.get("url") else ""
        date = f' (consulté le {e(s["consulte_le"])})' if s.get("consulte_le") else ""
        sources.append(f"<li>{e(libelle)}{date}{lien}</li>")
    if not sources:
        sources.append("<li>Aucune source externe n'a encore été collectée pour cette fiche.</li>")

    photo = photos.get(cid) or {}
    credit = ""
    if photo:
        credit = f'Photo : {e(photo.get("auteur"))} · {e(photo.get("licence"))} · Wikimedia'

    confiance = c.get("confiance") or "partiel"
    classe = {"documente": "ok", "partiel": "moyen", "faible": "faible"}.get(confiance, "moyen")
    description = (c.get("presentation") or c.get("surnom") or c.get("nom") or "")[:180]

    return GABARIT.format(
        nom=e(c.get("nom")), surnom=e(c.get("surnom")), id=e(cid), cycle=e(c.get("cycle")),
        famille="Épice" if c.get("type") == "epice" else "Culture vivrière",
        maj=e(maj), confiance=e(confiance), classe_confiance=classe,
        description=e(description), credit=credit,
        sommaire="".join(sommaire), sections="\n".join(sections),
        tutoriel=tutoriel, sources="".join(sources), limites=e(c.get("limites")),
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Génère les fiches cultures détaillées")
    p.add_argument("--verifier", action="store_true", help="ne rien écrire, signaler un écart")
    a = p.parse_args()

    cultures, meta = charger()
    photos_f = ROOT / "web" / "assets" / "cultures" / "_sources.json"
    photos = json.loads(photos_f.read_text(encoding="utf-8")) if photos_f.exists() else {}
    maj = meta.get("_maj") or "2026-10-21"

    SORTIE.mkdir(parents=True, exist_ok=True)
    ecarts = 0
    for cid, c in cultures.items():
        contenu = page(cid, c, photos, maj)
        dest = SORTIE / f"{cid}.html"
        if a.verifier:
            if not dest.exists() or dest.read_text(encoding="utf-8") != contenu:
                print(f"écart : {dest.name}")
                ecarts += 1
        else:
            dest.write_text(contenu, encoding="utf-8")
            print(f"écrit : {dest.relative_to(ROOT)} ({len(contenu)} o)")
    print(f"{len(cultures)} fiches · mise à jour {maj} · écarts : {ecarts}")
    return 1 if (a.verifier and ecarts) else 0


if __name__ == "__main__":
    raise SystemExit(main())

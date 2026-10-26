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
  <link rel="stylesheet" href="../assets/site.css?v=24">
  <link rel="stylesheet" href="../assets/fiche.css?v=4">
</head>
<body class="fiche-page">
<a class="skip" href="#fiche">Aller au contenu</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="../" aria-label="AGROGUIDCI, accueil">
      <span class="brand-mark"><svg class="logo-agro" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path class="logo-tige" d="M16 27.4V14.2" stroke="currentColor" stroke-width="2.9" stroke-linecap="round"/><path class="logo-feuille logo-feuille-h" d="M16 15c0-5.2 3.6-8.9 8.5-8.9 0 5.2-3.6 8.9-8.5 8.9Z" fill="currentColor"/><path class="logo-feuille logo-feuille-b" d="M16.2 19.2c0-4-2.9-7-6.9-7 0 4 2.9 7 6.9 7Z" fill="currentColor" fill-opacity=".62"/><circle class="logo-soleil" cx="17.4" cy="3.9" r="2.2" fill="#e8a33d"/></svg></span>
      <span class="brand-text">AGROGUIDCI</span>
    </a>
    <nav class="nav" aria-label="Navigation principale">
      <a class="navlink" href="../#cultures">Cultures &amp; épices</a>
      <a class="navlink" href="../#prix">Prix du kilo</a>
      <a class="navlink" href="../#actus">Actualités</a>
      <a class="navlink" href="../#tarifs">Tarifs</a>
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
        {photo_entete}
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
      <button class="btn btn-primary btn-lg" type="button" data-chat="ouvrir" data-culture="{id}" data-culture-libelle="{nom}" data-suggestions="{suggestions}">Poser une question sur cette culture</button>
      <a class="btn btn-ghost btn-lg" href="../#prix">Voir les prix au kilo</a>
    </section>
  </div>

  <!-- ===================== CHATBOX — AGENT EXPERT AGRONOME ===================== -->
  <dialog id="chatDialogue" class="chat-dialogue" aria-labelledby="chatTitre" aria-describedby="chatAide">
    <div class="chat-panneau">
      <header class="chat-entete">
        <div>
          <h2 id="chatTitre">Agent expert agronome</h2>
          <p id="chatCulture" class="chat-sous-titre" hidden></p>
        </div>
        <div class="chat-outils">
          <button type="button" id="chatNouveau" class="btn btn-ghost btn-sm">Nouvelle conversation</button>
          <button type="button" id="chatFermer" class="chat-fermer" aria-label="Fermer la conversation">×</button>
        </div>
      </header>

      <ol id="chatFil" class="chat-fil" aria-live="polite" aria-busy="false"></ol>

      <p id="chatEtat" class="chat-etat" role="status" aria-live="polite"></p>

      <div id="chatSuggestions" class="chat-suggestions" aria-label="Questions fréquentes"></div>

      <form id="chatForm" class="chat-form">
        <label class="sr-only" for="chatTexte">Votre question</label>
        <textarea id="chatTexte" rows="2" maxlength="2000" placeholder="Ex. : quelle variété choisir à Bouaké ?" required></textarea>
        <button type="submit" id="chatEnvoyer" class="btn btn-primary">Envoyer</button>
      </form>
      <p id="chatAide" class="chat-aide">Réponses de l'agent, avec ses sources et ses limites. Les échanges sont conservés 90 jours puis supprimés : n'indiquez pas de données sensibles.</p>
    </div>
  </dialog>

</main>

<footer class="site-footer">
  <div class="wrap">
    <p>AGROGUIDCI — conseil agricole pour la Côte d'Ivoire. <a href="../confidentialite.html">Politique de confidentialité</a></p>
  </div>
</footer>
<script src="../assets/chat.js?v=20" defer></script>
</body>
</html>
"""


# Questions proposées dans la chatbox ouverte depuis une fiche : elles portent sur
# les décisions que le producteur doit prendre, avec l'article correct du nom.
ARTICLES = {
    "voandzou": "le", "fonio": "le", "sesame": "le", "patatedouce": "la",
    "soja": "le", "igname": "l'", "plantain": "le", "poivre": "le",
    "gingembre": "le", "curcuma": "le", "piment": "le",
}
# Deuxième question : le point de vigilance propre à la culture (jamais générique).
POINT_CRITIQUE = {
    "voandzou": "Comment trier les graines avant de semer ?",
    "fonio": "Comment désherber sans abîmer le fonio ?",
    "sesame": "Comment éviter que les capsules s'ouvrent avant la récolte ?",
    "patatedouce": "Comment choisir des boutures saines ?",
    "soja": "Où vendre mon soja après la récolte ?",
    "igname": "Comment préparer les buttes et les semenceaux ?",
    "plantain": "Comment choisir les rejets au plantain ?",
    "poivre": "Où trouver un acheteur pour le poivre ?",
    "gingembre": "Comment éviter les pourritures du gingembre ?",
    "curcuma": "Comment sécher et transformer le curcuma ?",
    "piment": "Comment protéger le piment des pucerons ?",
}


def suggestions(cid: str, nom: str) -> str:
    """Les quatre questions proposées dans le chat de cette fiche."""
    article = ARTICLES.get(cid, "le")
    espace = "" if article.endswith("'") else " "
    return "|".join([
        f"Quand planter {article}{espace}{nom.lower()} ?",
        POINT_CRITIQUE.get(cid, "Quel est le point de vigilance principal ?"),
        "Quelle densité et quel écartement ?",
        "Comment conserver la récolte ?",
    ])


def e(t: object) -> str:
    return html.escape(str(t or ""), quote=True)


# Pictogrammes des étapes de tutoriel : dessins vectoriels originaux (aucune photo
# inventée), une icône par type de geste. Couleur héritée, décoratifs (aria-hidden).
_PICTO_ENTETE = ('<svg viewBox="0 0 28 28" fill="none" stroke="currentColor" '
                 'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
                 'aria-hidden="true" focusable="false">')
RACINE_FICHIERS = Path(__file__).resolve().parent.parent


def derives_webp(chemin: str) -> tuple[str, str] | None:
    """« assets/cultures/x.jpg » -> (« assets/cultures/480/x.webp », « .../960/x.webp »).

    Renvoie None si les dérivés n'existent pas sur disque : une <source> cassée
    afficherait une image vide, contrairement à un repli JPEG.
    """
    if not chemin.endswith(".jpg") or "/cultures/" not in chemin:
        return None
    base, nom = chemin.rsplit("/", 1)
    petit, grand = f"{base}/480/{nom[:-4]}.webp", f"{base}/960/{nom[:-4]}.webp"
    for rel in (petit, grand):
        if not (RACINE_FICHIERS / "web" / rel).exists():
            return None
    return petit, grand


PICTOS = {
    "parcelle": _PICTO_ENTETE + '<circle cx="8" cy="8" r="3"/><path d="M3 17h22M5 21h19M7 25h15"/></svg>',
    "preparation": _PICTO_ENTETE + '<path d="M3 22c4-9 10-9 14 0"/><circle cx="20" cy="8" r="1.3"/>'
                                   '<circle cx="24" cy="12" r="1.3"/><circle cx="18" cy="13" r="1.3"/></svg>',
    "semence": _PICTO_ENTETE + '<circle cx="9" cy="9" r="2.6"/><circle cx="16" cy="7" r="2"/>'
                               '<circle cx="21" cy="13" r="2.6"/><path d="M4 22h20"/></svg>',
    "plantation": _PICTO_ENTETE + '<path d="M3 22h22"/><path d="M14 22V11"/>'
                                  '<path d="M14 14c0-3 2.4-5.4 5.4-5.4 0 3-2.4 5.4-5.4 5.4Z"/></svg>',
    "entretien": _PICTO_ENTETE + '<path d="M4 24h20"/><path d="M14 24V7"/>'
                                 '<path d="M14 12c-3 0-5-2-5-4.5 3 0 5 2 5 4.5Z"/>'
                                 '<path d="M14 17c3 0 5-2 5-4.5-3 0-5 2-5 4.5Z"/></svg>',
    "sante": _PICTO_ENTETE + '<path d="M6 22C6 12 13 5 23 5c0 10-7 17-17 17Z"/>'
                             '<path d="M6 22 23 5"/><circle cx="12" cy="16" r="1.6"/></svg>',
    "recolte": _PICTO_ENTETE + '<path d="M5 12h18l-2 10H7z"/><path d="M10 12a4 4 0 0 1 8 0"/>'
                               '<path d="M10 16v3M14 16v3M18 16v3"/></svg>',
    "stockage": _PICTO_ENTETE + '<path d="M10 5h8v3l3 13H7l3-13z"/>'
                                '<path d="M10 5c0 2 1.8 3 4 3s4-1 4-3"/><path d="M11 16h6"/></svg>',
    "marche": _PICTO_ENTETE + '<circle cx="14" cy="14" r="8.5"/><path d="M14 9v10M11 12.5h6M11 16h6"/></svg>',
}


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


def section_fertilisation(fert: dict) -> str:
    """Tableau « quoi, combien, quand » — la partie la plus consultée d'une fiche."""
    apports = fert.get("apports") or []
    if not apports:
        return ""
    libelles = {"organique": "Organique", "mineral": "Minéral", "inoculant": "Inoculant"}
    lignes = []
    for a in apports:
        typ = a.get("type") or "mineral"
        lignes.append(
            '<tr data-type="%s">'
            '<td><span class="engrais-tag %s">%s</span><strong>%s</strong></td>'
            '<td class="dose">%s</td><td>%s</td><td>%s</td></tr>' % (
                e(typ), e(typ), e(libelles.get(typ, typ)), e(a.get("produit")),
                e(a.get("dose")), e(a.get("moment")), e(a.get("methode"))))
    principe = f'<p class="engrais-principe">{e(fert.get("principe"))}</p>' if fert.get("principe") else ""
    note = f'<p class="engrais-note">{e(fert.get("note"))}</p>' if fert.get("note") else ""
    liens = " · ".join(
        f'<a href="{e(s["url"])}" target="_blank" rel="noreferrer">{e(s["organisme"])}</a>'
        for s in (fert.get("sources") or []) if s.get("url"))
    sources = f'<p class="engrais-sources">Repères de fumure : {liens}</p>' if liens else ""
    return f'''    <section class="fiche-section fiche-engrais" id="fertilisation">
      <h2>Engrais : quoi, combien, quand</h2>
      {principe}
      <div class="engrais-defilement">
        <table class="engrais-table">
          <thead><tr><th scope="col">Apport</th><th scope="col">Dose</th><th scope="col">Quand</th><th scope="col">Comment</th></tr></thead>
          <tbody>{"".join(lignes)}</tbody>
        </table>
      </div>
      {note}
      {sources}
    </section>'''


def page(cid: str, c: dict, photos: dict, maj: str) -> str:
    sommaire, sections = [], []
    fert = c.get("fertilisation") or {}
    for cle, titre in TITRES:
        texte = (c.get(cle) or "").strip()
        if not texte and not (cle == "entretien" and fert.get("apports")):
            continue
        sommaire.append(f'<li><a href="#{cle}">{e(titre)}</a></li>')
        sections.append(f'''    <section class="fiche-section" id="{cle}">
      <h2>{e(titre)}</h2>
      <p>{e(texte)}</p>
    </section>''')
        if cle == "entretien":
            bloc_fert = section_fertilisation(fert)
            if bloc_fert:
                sommaire.append('<li><a href="#fertilisation">Engrais : doses et moments</a></li>')
                sections.append(bloc_fert)
    sommaire.append('<li><a href="#tutoriel">Tutoriel étape par étape</a></li>')
    sommaire.append('<li><a href="#sources">Sources et limites</a></li>')

    etapes_photos = (photos.get(cid) or {}).get("etapes") or {}

    def figure_etape(icone: str | None) -> str:
        ph = etapes_photos.get(icone or "")
        if not ph or not ph.get("fichier"):
            return ""
        credit = " · ".join(x for x in (ph.get("auteur"), ph.get("licence")) if x)
        lien = ph.get("page") or ""
        libelle = f'<a href="{e(lien)}" target="_blank" rel="noreferrer">Wikimedia Commons</a>' if lien else ""
        fichier = ph["fichier"]
        alt = f'{e(c.get("nom"))} — illustration de cette étape'
        derives = derives_webp(fichier)
        if derives:
            petit, grand = derives
            image = (f'<picture><source type="image/webp" '
                     f'srcset="../{e(petit)} 480w, ../{e(grand)} 960w" '
                     f'sizes="(max-width: 560px) 92vw, 520px">'
                     f'<img src="../{e(fichier)}" alt="{alt}" loading="lazy" decoding="async">'
                     f'</picture>')
        else:
            image = f'<img src="../{e(fichier)}" alt="{alt}" loading="lazy" decoding="async">'
        return (f'<figure class="tuto-photo">{image}<figcaption>{e(credit)}'
                f'{" · " + libelle if libelle else ""}</figcaption></figure>')

    tutoriel = "\n".join(
        '<li class="tuto-etape">'
        f'<span class="tuto-picto">{PICTOS.get(etape.get("icone") or "", "")}</span>'
        f'<div class="tuto-corps"><strong>{e(etape.get("titre"))}</strong>'
        f'<p>{e(etape.get("simple") or etape.get("texte"))}</p>'
        f'{figure_etape(etape.get("icone"))}</div>'
        "</li>"
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

    # photo d'en-tête : dérivés WebP si présents, sinon le JPEG d'origine
    jpg_entete = f"assets/cultures/{cid}.jpg"
    derives = derives_webp(jpg_entete)
    if derives:
        petit, grand = derives
        photo_entete = (
            f'<picture><source type="image/webp" '
            f'srcset="../{petit} 480w, ../{grand} 960w" '
            f'sizes="(max-width: 820px) 100vw, 44vw">'
            f'<img src="../{jpg_entete}" alt="{e(c.get("nom"))} — photographie réelle" '
            f'width="1200" height="750" fetchpriority="high" decoding="async">'
            f'</picture>'
        )
    else:
        photo_entete = (
            f'<img src="../{jpg_entete}" alt="{e(c.get("nom"))} — photographie réelle" '
            f'width="1200" height="750" decoding="async">'
        )

    confiance = c.get("confiance") or "partiel"
    classe = {"documente": "ok", "partiel": "moyen", "faible": "faible"}.get(confiance, "moyen")
    description = (c.get("presentation") or c.get("surnom") or c.get("nom") or "")[:180]

    return GABARIT.format(
        nom=e(c.get("nom")), surnom=e(c.get("surnom")), id=e(cid), cycle=e(c.get("cycle")),
        famille={"epice": "Épice", "legume": "Légume", "fruit": "Fruit"}.get(
            c.get("type"), "Culture vivrière"),
        maj=e(maj), confiance=e(confiance), classe_confiance=classe,
        description=e(description), credit=credit, photo_entete=photo_entete,
        sommaire="".join(sommaire), sections="\n".join(sections),
        tutoriel=tutoriel, sources="".join(sources), limites=e(c.get("limites")),
        suggestions=suggestions(cid, c.get("nom") or cid),
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

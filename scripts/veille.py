"""veille.py — détecte les nouveautés publiées par les sources agricoles ivoiriennes.

Principe : on ne fabrique rien. On compare ce que publient les organismes de
référence (FIRCA, ANADER, ministère de l'Agriculture, OCPV/PAM Agro, PNIA) avec
l'état mémorisé lors du passage précédent, et on écrit les NOUVEAUX titres dans
veille/candidats.jsonl, avec leur URL.

Le script ne publie jamais rien sur le site : il propose. La mise en ligne d'une
nouvelle fiche reste une décision (revue de la source, puis ajout dans
web/assets/cultures.json et `python scripts/gen_index.py`).

    python scripts/veille.py              # détecte et écrit les candidats
    python scripts/veille.py --etat       # affiche l'état mémorisé, sans réseau
    python scripts/veille.py --resume 5   # résumé des 5 derniers candidats
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VEILLE = ROOT / "veille"
ETAT = VEILLE / "etat-sources.json"
CANDIDATS = VEILLE / "candidats.jsonl"

SOURCES = [
    ("FIRCA", "https://firca.ci/filieres-agricoles/"),
    ("FIRCA — légumes et soja", "https://firca.ci/filieres-agricoles/legumes/"),
    ("ANADER", "https://www.anader.ci/"),
    ("Ministère de l'Agriculture", "https://www.agriculture.gouv.ci/"),
    ("PAM Agro — prix OCPV", "https://www.pamdagro.ci/index.php/en/produits-vivriers/ocpv"),
    ("Portail officiel — publications", "https://www.gouv.ci/"),
]

MOTS = ("culture", "filiere", "filière", "prix", "appui", "financement", "semence", "cooperative",
        "coopérative", "export", "campagne", "formation", "rendement", "variete", "variété",
        "epice", "épice", "biologique", "irrigation", "transformation")
UA = {"User-Agent": "AGROGUIDCI/1.2 (veille agricole; contact aicmaxter@gmail.com)"}


def sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def telecharger(url: str, timeout: float = 30.0) -> str | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def titres(html: str, base: str) -> list[dict]:
    """Titres de niveau 2/3 et liens dont le libellé parle d'agriculture."""
    trouves: list[dict] = []
    vus: set[str] = set()
    for balise, motif in (("h2", r"<h[12][^>]*>(.*?)</h[12]>"), ("h3", r"<h[23][^>]*>(.*?)</h[23]>")):
        for m in re.finditer(motif, html, flags=re.S | re.I):
            texte = re.sub(r"<[^>]+>", " ", m.group(1))
            texte = re.sub(r"\s+", " ", texte).strip()
            if 15 <= len(texte) <= 180 and sans_accents(texte) not in vus:
                vus.add(sans_accents(texte))
                trouves.append({"niveau": balise, "titre": texte, "lien": base})
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.S | re.I):
        texte = re.sub(r"<[^>]+>", " ", m.group(2))
        texte = re.sub(r"\s+", " ", texte).strip()
        if not (12 <= len(texte) <= 160):
            continue
        if not any(mot in sans_accents(texte) for mot in MOTS):
            continue
        if sans_accents(texte) in vus:
            continue
        vus.add(sans_accents(texte))
        lien = m.group(1)
        if lien.startswith("/"):
            lien = re.sub(r"^(https?://[^/]+).*$", r"\1", base).rstrip("/") + lien
        trouves.append({"niveau": "lien", "titre": texte, "lien": lien})
    return trouves[:60]


def empreinte(items: list[dict]) -> str:
    brut = "|".join(sorted(sans_accents(i["titre"]) for i in items))
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def charger_etat() -> dict:
    if ETAT.exists():
        try:
            return json.loads(ETAT.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def main() -> int:
    p = argparse.ArgumentParser(description="Veille des sources agricoles ivoiriennes")
    p.add_argument("--etat", action="store_true", help="afficher l'état mémorisé sans réseau")
    p.add_argument("--resume", type=int, default=0, help="afficher les N derniers candidats")
    a = p.parse_args()

    VEILLE.mkdir(exist_ok=True)
    etat = charger_etat()

    if a.etat:
        if not etat:
            print("Aucun état mémorisé : lancer `python scripts/veille.py` une première fois.")
        for url, v in etat.items():
            print(f"- {v.get('nom', url)}\n  {url}\n  {v.get('items', 0)} titre(s) · vu le {v.get('vu_le', '?')}")
        return 0

    if a.resume:
        if not CANDIDATS.exists():
            print("Aucun candidat enregistré.")
            return 0
        lignes = [json.loads(l) for l in CANDIDATS.read_text(encoding="utf-8").splitlines() if l.strip()]
        for c in lignes[-a.resume:]:
            print(f"[{c['ts']}] {c['source']} — {c['titre']}\n   {c['lien']}")
        return 0

    nouveaux_total = 0
    for nom, url in SOURCES:
        html = telecharger(url)
        if html is None:
            print(f"! {nom} injoignable ({url}) — état inchangé")
            continue
        items = titres(html, url)
        emp = empreinte(items)
        ancien = etat.get(url, {})
        deja = {sans_accents(t) for t in ancien.get("titres", [])}
        nouveautes = [i for i in items if sans_accents(i["titre"]) not in deja]
        if ancien and ancien.get("empreinte") != emp:
            print(f"+ {nom} : {len(nouveautes)} nouveau(x) titre(s)")
            with CANDIDATS.open("a", encoding="utf-8") as f:
                for i in nouveautes[:15]:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": nom,
                                        "titre": i["titre"], "lien": i["lien"], "niveau": i["niveau"]},
                                       ensure_ascii=False) + "\n")
                    nouveaux_total += 1
        else:
            print(f"= {nom} : {len(items)} titre(s), rien de nouveau")
        etat[url] = {"nom": nom, "empreinte": emp, "items": len(items),
                     "titres": [i["titre"] for i in items][:60],
                     "vu_le": time.strftime("%Y-%m-%dT%H:%M:%S")}
        time.sleep(1.0)

    ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(etat)} source(s) suivie(s) · {nouveaux_total} nouveau(x) candidat(s) dans {CANDIDATS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

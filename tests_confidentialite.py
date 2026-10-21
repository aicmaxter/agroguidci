"""tests_confidentialite.py — conformité « données personnelles » et vitrine v4.

    python tests_confidentialite.py

Aucun réseau, aucun appel de modèle. Trois familles de contrôles observables :
  1. masquage des données personnelles dans les journaux (confidentialite.py) ;
  2. application des durées de conservation (scripts/purge_donnees.py) ;
  3. mentions légales obligatoires et nouveaux blocs de la page d'accueil.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import confidentialite  # noqa: E402
from confidentialite import masquer  # noqa: E402

RESULTATS: list[tuple[str, bool, str]] = []


def verifie(nom: str, condition: bool, detail: object = "") -> None:
    RESULTATS.append((nom, bool(condition), str(detail)))


# ------------------------------------------------------------------ 1. masquage
texte_tel = "joignable au 07 12 34 56 78"
verifie("téléphone 10 chiffres masqué",
        "07 12 34 56 78" not in masquer(texte_tel) and "masqué" in masquer(texte_tel))
verifie("téléphone +225 masqué", "01 02 03 04 05" not in masquer("appelez +225 01 02 03 04 05"))
verifie("e-mail masqué", "koffi@exemple.ci" not in masquer("écrire à koffi@exemple.ci"))
verifie("prix et surfaces conservés",
        masquer("250 000 FCFA pour 2 hectares, 1,5 t/ha") == "250 000 FCFA pour 2 hectares, 1,5 t/ha")
verifie("identifiant de mission conservé",
        "mis_20261021-012420" in masquer("mission mis_20261021-012420 duree 103 s"))
verifie("texte vide géré", masquer("") == "")
verifie("dictionnaire imbriqué masqué",
        "07 12 34 56 78" not in json.dumps(confidentialite.masquer_champs({"a": {"tel": "07 12 34 56 78"}})))

# ------------------------------------------------------------------ 2. purge
sys.path.insert(0, str(ROOT / "scripts"))
import purge_donnees as purge  # noqa: E402

bac = Path(tempfile.mkdtemp(prefix="purge-test-"))
purge.OUT = bac / "out"
purge.DATA = bac / "data"
purge.OUT.mkdir(parents=True)
(purge.DATA / "missions").mkdir(parents=True)
(purge.DATA / "producteurs").mkdir(parents=True)

vieille_mission = purge.OUT / "20200101-120000-vieille"
vieille_mission.mkdir()
(vieille_mission / "rapport.md").write_text("x" * 100, encoding="utf-8")
recente = purge.OUT / (time.strftime("%Y%m%d-%H%M%S") + "-recente")
recente.mkdir()
(recente / "rapport.md").write_text("x" * 50, encoding="utf-8")
(purge.OUT / "tests-r1").mkdir()

candidats = [p.name for p in purge.dossiers_missions(90)]
verifie("mission ancienne détectée", "20200101-120000-vieille" in candidats, candidats)
verifie("mission récente conservée", not any("recente" in c for c in candidats), candidats)
verifie("dossier de test exclu", "tests-r1" not in candidats, candidats)

vieux_jsonl = purge.DATA / "missions" / "mis_20200101-120000.jsonl"
vieux_jsonl.write_text('{"ts":"2020-01-01T00:00:00"}\n', encoding="utf-8")
os.utime(vieux_jsonl, (time.time() - 200 * 86400,) * 2)
verifie("fichier mission hors fenêtre détecté", len(purge.missions_jsonl(90)) == 1)

vieux_prod = purge.DATA / "producteurs" / "koffi.json"
vieux_prod.write_text("{}", encoding="utf-8")
os.utime(vieux_prod, (time.time() - 800 * 86400,) * 2)
(purge.DATA / "producteurs" / "recent.json").write_text("{}", encoding="utf-8")
verifie("dossier producteur > 24 mois détecté",
        [p.name for p in purge.dossiers_producteurs(24)] == ["koffi.json"])

journal = purge.OUT / "journal-experts.jsonl"
journal.write_text('{"ts":"2020-01-01T00:00:00","instruction":"vieux"}\n'
                   '{"ts":"' + time.strftime("%Y-%m-%dT%H:%M:%S") + '","instruction":"recent"}\n',
                   encoding="utf-8")
gardees, supprimees = purge.filtrer_journal(journal, 365, executer=False)
verifie("journal : la simulation ne supprime rien",
        supprimees == 1 and len(journal.read_text(encoding="utf-8").splitlines()) == 2,
        f"gardees={gardees} supprimees={supprimees}")
gardees2, supprimees2 = purge.filtrer_journal(journal, 365, executer=True)
contenu = journal.read_text(encoding="utf-8")
verifie("journal : effacement réel garde la ligne récente",
        supprimees2 == 1 and "recent" in contenu and "vieux" not in contenu, contenu[:80])
verifie("journal : sauvegarde créée", bool(list(purge.OUT.glob("journal-experts.jsonl.bak-*"))))

# ------------------------------------------------------------------ 3. page d'accueil
accueil = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
css = (ROOT / "web" / "assets" / "site.css").read_text(encoding="utf-8")
verifie("accueil : section actualités", 'id="actualites"' in accueil)
verifie("accueil : prix au kilo", 'id="prix"' in accueil and "prixBody" in accueil)
verifie("accueil : cultures à découvrir", 'id="cultures"' in accueil and "Voandzou" in accueil)
verifie("accueil : quatre offres",
        all(x in accueil for x in ("Découverte", "Crédits", "Suivi personnalisé", "Professionnels")))
verifie("accueil : crédits à 599 FCFA", "599" in accueil and "10 conseils" in accueil)
verifie("accueil : consentement explicite", 'id="consent"' in accueil and "confidentialite.html" in accueil)
verifie("accueil : compteur de crédits", 'id="creditsCount"' in accueil)
verifie("accueil : plus d'onglets conseillers", "Les 7 agents" not in accueil and "agents-grid" not in accueil)
verifie("accueil : palette verte", "--green-600" in css and "--orange:" not in css)
verifie("accueil : fichiers JS chargés", "assets/ui.js" in accueil and "assets/motion.js" in accueil)
verifie("accueil : section épices", 'id="epices"' in accueil and "Poivre noir" in accueil)
verifie("accueil : huit cartes cultures/épices", accueil.count('class="crop reveal"') == 8, accueil.count('class="crop reveal"'))
verifie("accueil : photos réelles référencées",
        all(f"assets/cultures/{c}.jpg" in accueil for c in
            ("poivre", "gingembre", "curcuma", "piment", "voandzou", "fonio", "sesame", "patatedouce")))
verifie("accueil : crédits photo Wikimedia", accueil.count("Wikimedia Commons") == 8, accueil.count("Wikimedia Commons"))
verifie("accueil : bandeau de prix défilant", 'id="prixTicker"' in accueil)
verifie("accueil : section prix sur fond vert", 'class="section band-green" id="prix"' in accueil)
verifie("accueil : hero vert", ".hero {" in css and "#0b3a22" in css)
verifie("photos présentes sur le disque",
        all((ROOT / "web" / "assets" / "cultures" / f"{c}.jpg").exists() for c in
            ("poivre", "gingembre", "curcuma", "piment", "voandzou", "fonio", "sesame", "patatedouce")))
_lic = json.loads((ROOT / "web" / "assets" / "cultures" / "_sources.json").read_text(encoding="utf-8"))
verifie("licences photo renseignées", all(v.get("licence") and v.get("auteur") for v in _lic.values()))

# ------------------------------------------------------------------ 4. page légale
legal_path = ROOT / "web" / "confidentialite.html"
legal = legal_path.read_text(encoding="utf-8") if legal_path.exists() else ""
verifie("politique de confidentialité publiée", legal_path.exists())
for attendu, libelle in (
    ("2013-450", "référence à la loi 2013-450"),
    ("19 juin 2013", "date de la loi"),
    ("autoritedeprotection.ci", "autorité de contrôle"),
    ("2015-79", "décret d'application"),
    ("DeepSeek", "sous-traitant modèle de langage"),
    ("Open-Meteo", "sous-traitant météo"),
    ("Vercel", "hébergeur"),
    ("Transferts hors de Côte d'Ivoire", "encadrement des transferts"),
    ("Combien de temps", "durées de conservation"),
    ("Vos droits", "droits des personnes"),
    ("Droit d'accès", "droit d'accès"),
    ("Droit à l'effacement", "droit à l'effacement"),
    ("30 jours", "délai de réponse"),
    ("masqu", "masquage des journaux"),
    ("Chiffrement en transit", "mesure de sécurité"),
    ("Mineurs", "mention des mineurs"),
):
    verifie(f"politique : {libelle}", attendu in legal)

# ------------------------------------------------------------------ bilan
print()
echecs = [r for r in RESULTATS if not r[1]]
for nom, ok, detail in RESULTATS:
    print(f"{'OK   ' if ok else 'ECHEC'}  {nom}" + (f"  [{detail[:120]}]" if not ok else ""))
print(f"\n{len(RESULTATS) - len(echecs)}/{len(RESULTATS)} contrôles OK · échecs : {len(echecs)}")

rapport = ROOT / "out" / "tests-confidentialite" / time.strftime("%Y%m%d-%H%M%S") / "rapport.md"
rapport.parent.mkdir(parents=True, exist_ok=True)
rapport.write_text("# Contrôles confidentialité et vitrine v4\n\n"
                   f"{len(RESULTATS) - len(echecs)}/{len(RESULTATS)} OK\n\n"
                   + "\n".join(f"- {'OK' if ok else 'ECHEC'} — {nom}" for nom, ok, _ in RESULTATS),
                   encoding="utf-8")
print(f"rapport : {rapport}")
raise SystemExit(0 if not echecs else 1)

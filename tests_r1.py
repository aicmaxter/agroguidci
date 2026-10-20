"""
tests_r1.py — tests de securite ciblés de la correction R1 (AGROGUIDCI).

Objet : verifier qu'aucune demande utilisateur ne peut faire lire un fichier
local arbitraire par `outils.analyser_tableau()`, et qu'un fichier depose dans
le canal d'import autorise reste analysable.

    python tests_r1.py

Aucun test ne lance de mission agricole, n'appelle le reseau, ni n'ecrit hors de
`out/tests-r1/` et d'un dossier temporaire.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import outils  # noqa: E402

SORTIE = ROOT / "out" / "tests-r1"
CONTENU_SECRET = "SECRET-CONTENU-INTERDIT"
CSV_VALIDE = "date;qte;prix\n2026-01;120;250\n2026-02;140;260\n2026-03;90;245\n"


def _dossier(nom: str) -> Path:
    d = SORTIE / time.strftime("%Y%m%d-%H%M%S") / nom
    d.mkdir(parents=True, exist_ok=True)
    return d


def _refus(sortie: str) -> bool:
    """Une demande refusee ne doit jamais produire de statistiques."""
    return (sortie.startswith(outils.MARQUEUR_ECHEC)
            and "FICHIER ABSENT" in sortie
            and "| colonne |" not in sortie)


def _cas_refus(nom: str, demande: str) -> dict:
    d = _dossier(nom)
    sortie = outils.analyser_tableau(demande, "", d)
    (d / "sortie-outil.md").write_text(sortie, encoding="utf-8")
    ok = _refus(sortie) and CONTENU_SECRET not in sortie
    return {
        "cas": nom,
        "demande": demande,
        "attendu": "refus + ECHEC_OUTIL + FICHIER ABSENT, aucune statistique",
        "verdict": "OK" if ok else "ECHEC",
        "preuve": str(d / "sortie-outil.md"),
        "sortie": sortie.splitlines()[0][:160] if sortie else "(vide)",
    }


def _preparer_piege() -> tuple[Path, Path]:
    """Fichier CSV sensible hors du canal d'import + dossier de sortie isole."""
    base = Path(tempfile.mkdtemp(prefix="r1-piege-"))
    secret = base / "recolte-secrete.csv"
    secret.write_text(CSV_VALIDE.replace("2026-01;120;250", f"2026-01;{CONTENU_SECRET};250"),
                      encoding="utf-8")
    return base, secret


def t01_absolu_windows(secret: Path) -> dict:
    return _cas_refus("t01-absolu-windows", f"analyse mon tableau {secret}")


def t02_absolu_windows_slash() -> dict:
    return _cas_refus("t02-absolu-slash", "analyse C:/Users/Public/recolte.csv")


def t03_unc() -> dict:
    return _cas_refus("t03-unc", r"analyse \\serveur\partage\recolte.csv")


def t04_relatif_parent() -> dict:
    return _cas_refus("t04-relatif-parent", r"analyse ..\..\recolte.csv")


def t05_relatif_courant() -> dict:
    return _cas_refus("t05-relatif-courant", r"analyse .\recolte.csv")


def t06_absolu_posix() -> dict:
    return _cas_refus("t06-absolu-posix", "analyse /etc/passwd.csv")


def t07_sous_dossier() -> dict:
    return _cas_refus("t07-sous-dossier", "analyse sous/ventes.csv")


def t08_nom_absent_du_canal() -> dict:
    """Nom simple mais fichier non depose : refus explicite, rien d'invente."""
    return _cas_refus("t08-nom-absent", "analyse ventes.csv")


def t09_lien_sortant(base: Path, secret: Path) -> dict:
    """Un lien dans le canal d'import ne doit pas permettre de sortir du dossier."""
    canal = base / "imports"
    canal.mkdir(exist_ok=True)
    lien = canal / "passe-partout.csv"
    try:
        if not lien.exists():
            os.symlink(secret, lien)
    except (OSError, NotImplementedError, AttributeError) as e:
        return {"cas": "t09-lien-sortant", "demande": "-", "attendu": "refus",
                "verdict": "NON APPLICABLE", "preuve": "-",
                "sortie": f"creation de lien impossible sous Windows : {type(e).__name__}"}
    ancien = os.environ.get("AGRO_IMPORT_DIR")
    os.environ["AGRO_IMPORT_DIR"] = str(canal)
    try:
        d = _dossier("t09-lien-sortant")
        sortie = outils.analyser_tableau("analyse passe-partout.csv", "", d)
        (d / "sortie-outil.md").write_text(sortie, encoding="utf-8")
        ok = _refus(sortie) and CONTENU_SECRET not in sortie
        return {"cas": "t09-lien-sortant", "demande": "analyse passe-partout.csv",
                "attendu": "refus (lien hors canal)", "verdict": "OK" if ok else "ECHEC",
                "preuve": str(d / "sortie-outil.md"),
                "sortie": sortie.splitlines()[0][:160]}
    finally:
        if ancien is None:
            os.environ.pop("AGRO_IMPORT_DIR", None)
        else:
            os.environ["AGRO_IMPORT_DIR"] = ancien


def t10_canal_autorise(base: Path) -> dict:
    """Un fichier DEPOSE dans le canal d'import reste analysable."""
    canal = base / "imports-autorises"
    canal.mkdir(exist_ok=True)
    (canal / "ventes.csv").write_text(CSV_VALIDE, encoding="utf-8")
    ancien = os.environ.get("AGRO_IMPORT_DIR")
    os.environ["AGRO_IMPORT_DIR"] = str(canal)
    try:
        d = _dossier("t10-canal-autorise")
        sortie = outils.analyser_tableau("analyse ventes.csv", "", d)
        (d / "sortie-outil.md").write_text(sortie, encoding="utf-8")
        stats = "| colonne |" in sortie
        origine_ok = "canal d'import autorise : ventes.csv" in sortie
        recopie = (d / "analyse.csv").exists()
        chemin_absolu = str(canal) in sortie
        ok = stats and origine_ok and recopie and not chemin_absolu
        return {"cas": "t10-canal-autorise", "demande": "analyse ventes.csv",
                "attendu": "statistiques produites, origine = ventes.csv, aucun chemin absolu",
                "verdict": "OK" if ok else "ECHEC", "preuve": str(d / "sortie-outil.md"),
                "sortie": (f"statistiques={stats} origine={origine_ok} recopie={recopie} "
                           f"chemin_absolu_divulgue={chemin_absolu}")}
    finally:
        if ancien is None:
            os.environ.pop("AGRO_IMPORT_DIR", None)
        else:
            os.environ["AGRO_IMPORT_DIR"] = ancien


def t11_csv_inline() -> dict:
    """Regression : un tableau colle dans la demande reste analyse (sans fichier)."""
    d = _dossier("t11-csv-inline")
    demande = "voici mes chiffres\nqte;prix\n120;250\n140;260\n90;245\n33;240"
    sortie = outils.analyser_tableau(demande, "", d)
    (d / "sortie-outil.md").write_text(sortie, encoding="utf-8")
    ok = "| colonne |" in sortie and "bloc CSV de la demande" in sortie
    return {"cas": "t11-csv-inline", "demande": demande.replace("\n", " / "),
            "attendu": "statistiques sur le texte fourni", "verdict": "OK" if ok else "ECHEC",
            "preuve": str(d / "sortie-outil.md"), "sortie": sortie.splitlines()[0][:160]}


def t12_lien_dur(base: Path, secret: Path) -> dict:
    """R1-B : un lien dur dans le canal ne doit pas donner acces au fichier d'origine.

    Creation sans privilege : os.link (equivalent de `mklink /H`), cree sur le meme
    volume que le fichier cible (dossier temporaire du poste).
    """
    canal = base / "imports-liens-durs"
    canal.mkdir(exist_ok=True)
    lien = canal / "raccourci.csv"
    try:
        if lien.exists():
            lien.unlink()
        os.link(secret, lien)
    except (OSError, NotImplementedError, AttributeError) as e:
        return {"cas": "t12-lien-dur", "demande": "analyse raccourci.csv",
                "attendu": "refus + FICHIER REFUSE, aucune statistique",
                "verdict": "NON APPLICABLE", "preuve": "-",
                "sortie": f"creation du lien dur impossible : {type(e).__name__}: {e}"}
    ancien = os.environ.get("AGRO_IMPORT_DIR")
    os.environ["AGRO_IMPORT_DIR"] = str(canal)
    try:
        d = _dossier("t12-lien-dur")
        sortie = outils.analyser_tableau("analyse raccourci.csv", "", d)
        (d / "sortie-outil.md").write_text(sortie, encoding="utf-8")
        refuse = (sortie.startswith(outils.MARQUEUR_ECHEC)
                  and "FICHIER REFUSE" in sortie
                  and "lien dur" in sortie.lower())
        sans_stats = "| colonne |" not in sortie
        sans_secret = CONTENU_SECRET not in sortie
        # controle direct du garde-fou de chemin
        chemin_refuse = outils._chemin_import_autorise("raccourci.csv") is None
        ok = refuse and sans_stats and sans_secret and chemin_refuse
        return {"cas": "t12-lien-dur", "demande": "analyse raccourci.csv",
                "attendu": "refus (lien dur), aucune statistique, aucun contenu",
                "verdict": "OK" if ok else "ECHEC", "preuve": str(d / "sortie-outil.md"),
                "sortie": (f"refus={refuse} sans_stats={sans_stats} sans_secret={sans_secret} "
                           f"chemin_refuse={chemin_refuse} | {sortie.splitlines()[0][:90]}")}
    finally:
        if ancien is None:
            os.environ.pop("AGRO_IMPORT_DIR", None)
        else:
            os.environ["AGRO_IMPORT_DIR"] = ancien


def main() -> int:
    base, secret = _preparer_piege()
    resultats = [
        t01_absolu_windows(secret),
        t02_absolu_windows_slash(),
        t03_unc(),
        t04_relatif_parent(),
        t05_relatif_courant(),
        t06_absolu_posix(),
        t07_sous_dossier(),
        t08_nom_absent_du_canal(),
        t09_lien_sortant(base, secret),
        t10_canal_autorise(base),
        t11_csv_inline(),
        t12_lien_dur(base, secret),
    ]
    echecs = [r for r in resultats if r["verdict"] == "ECHEC"]
    sortie = SORTIE / time.strftime("%Y%m%d-%H%M%S") / "rapport-r1.md"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    lignes = ["# Tests de securite R1 — analyser_tableau", "",
              f"Date : {time.strftime('%Y-%m-%d %H:%M:%S')} · "
              f"{len(resultats)} cas · {len(echecs)} echec(s)", "",
              "| cas | demande | attendu | verdict | sortie observee |",
              "|---|---|---|---|---|"]
    for r in resultats:
        lignes.append(f"| {r['cas']} | `{r['demande'][:70]}` | {r['attendu']} | "
                      f"**{r['verdict']}** | {r['sortie'][:110]} |")
    lignes += ["", "## Preuves", ""]
    lignes += [f"- {r['cas']} : `{r['preuve']}`" for r in resultats]
    sortie.write_text("\n".join(lignes) + "\n", encoding="utf-8")

    for r in resultats:
        print(f"{r['verdict']:<16} {r['cas']:<24} {r['sortie'][:100]}")
    print(f"\nrapport : {sortie}")
    print(f"echecs : {len(echecs)}")
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(main())

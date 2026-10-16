"""
supervision.py — tableau de bord et journaux d'execution d'AGROGUIDCI.

Vue d'ensemble du systeme : qui est en ligne, avec quels droits, ce que chaque
mission a mobilise, et ce qui attend une decision humaine.

    python supervision.py --etat          # agents reels vus par l'orchestrateur
    python supervision.py --charte        # responsabilites, outils autorises, actions sensibles
    python supervision.py --coherence     # SOUL.md <-> experts.py <-> outils.py
    python supervision.py --runs 10       # dernieres missions (depuis out/*/trace.json)
    python supervision.py --validations   # actions sensibles en attente
    python supervision.py --journal 20    # dernieres lignes de out/supervision.jsonl
    python supervision.py --tout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _charge_json(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def etat() -> str:
    from agrokit import Orchestrateur
    orch = Orchestrateur()
    lignes = [f"# Etat du reseau — {orch.base}", ""]
    if not orch.health():
        return "\n".join(lignes + ["**Orchestrateur injoignable** — demarrer avec "
                                   "`python demarrer_agroguidci.py`."])
    agents = orch.agents()
    agro = [a for a in agents if "AGROGUIDCI" in (a.get("name") or "").upper()
            or "agro-" in (a.get("agent_id") or "")]
    lignes += ["| agent | statut | capacites | taches reussies / echouees | vu il y a |",
               "|---|---|---|---|---|"]
    for a in sorted(agro, key=lambda x: x.get("agent_id") or ""):
        lignes.append(f"| {a.get('name')} (`{a.get('agent_id')}`) | {a.get('status')} "
                      f"| {', '.join(a.get('capabilities') or [])} "
                      f"| {a.get('tasks_done', '?')} / {a.get('tasks_failed', '?')} "
                      f"| {a.get('last_seen_age_s', '?')} s |")
    autres = [a for a in agents if a not in agro]
    lignes += ["", f"{len(agro)} agent(s) AGROGUIDCI · {len(autres)} autre(s) agent(s) du lab "
                   f"({', '.join((a.get('name') or '?') for a in autres) or '-'})."]
    taches = _taches_recentes()
    if taches:
        lignes += ["", "## Dernieres taches vues par l'orchestrateur", "",
                   "| tache | capacite | agent | statut | taille |", "|---|---|---|---|---|"]
        lignes += [f"| {t['task_id']} | {t['capability']} | {t['agent_id'] or '-'} | {t['status']} "
                   f"| {len(t['result'] or '')} car. |" for t in taches[:10]]
    return "\n".join(lignes)


def _taches_recentes(limite: int = 10) -> list[dict]:
    import urllib.request
    from agrokit import ADMIN_KEY, ORCH
    try:
        req = urllib.request.Request(f"{ORCH}/api/v1/tasks", headers={"X-API-Key": ADMIN_KEY})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data.get("data") or {}).get("tasks") or []
    except Exception:
        return []


def charte() -> str:
    from experts import charte as _charte
    lignes = ["# Charte de gouvernance AGROGUIDCI", "",
              "| agent | role | capacites | outils autorises | actions sensibles |",
              "|---|---|---|---|---|"]
    for c in _charte():
        lignes.append(f"| {c['agent']} | {c['role']} | {', '.join(c['capacites'])} "
                      f"| {', '.join(c['outils_autorises']) or '-'} "
                      f"| {', '.join(c['actions_sensibles']) or 'aucune'} |")
    lignes += ["", "## Limites de mandat declarees", ""]
    for c in _charte():
        lignes.append(f"- **{c['agent'].split(' ')[-1]}** : {c['limite_de_mandat']}")
    return "\n".join(lignes)


def coherence() -> str:
    """Confronte la constitution (SOUL.md), la gouvernance (experts.py) et les outils
    reellement installes (table de permissions -> outils.py).

    But : interdit qu'une specification soit presentee comme active alors que l'outil
    n'existe pas, et qu'un agent tourne sans fiche de gouvernance.
    """
    from experts import EXPERTISES
    from permissions import MATRICE, NATURE_OUTILS

    soul = ROOT / "SOUL.md"
    texte = soul.read_text(encoding="utf-8") if soul.exists() else ""
    reels = set(NATURE_OUTILS)
    alertes: list[str] = []
    lignes = ["# Coherence constitution / gouvernance / outils", "",
              f"Source : `{'SOUL.md' if texte else 'ABSENT'}` · {len(EXPERTISES)} agents · "
              f"{len(reels)} outils reellement installes", "",
              "| agent | documente dans SOUL.md | outils declares | competences | conduite d'echec |",
              "|---|---|---|---|---|"]
    utilises: set[str] = set()
    for cle, e in EXPERTISES.items():
        doc = bool(texte) and (e.agent_id in texte or f"`{cle}`" in texte or e.nom in texte)
        inconnus = [o for o in e.outils if o not in reels]
        utilises |= set(e.outils)
        if not doc:
            alertes.append(f"{cle} : agent sans fiche dans SOUL.md")
        if inconnus:
            alertes.append(f"{cle} : outil(s) declare(s) mais inexistant(s) -> {', '.join(inconnus)}")
        if not e.competences:
            alertes.append(f"{cle} : aucune competence declaree")
        if not e.failure_behavior:
            alertes.append(f"{cle} : aucune conduite d'echec declaree")
        for o in e.actions_sensibles:
            if o not in reels:
                alertes.append(f"{cle} : action sensible « {o} » inexistante dans outils.py")
                continue
            modes = {str((MATRICE.get(a) or {}).get("mode", "?")) for a in NATURE_OUTILS[o]}
            if "validation_humaine" not in modes:
                alertes.append(f"{cle} : « {o} » est declaree sensible mais la matrice ne la "
                               f"classe pas en validation_humaine (modes: {', '.join(sorted(modes))})")
        lignes.append(f"| {e.nom} (`{cle}`) | {'oui' if doc else '**NON**'} "
                      f"| {', '.join(e.outils) or 'aucun outil'} "
                      f"| {len(e.competences)} | {'oui' if e.failure_behavior else '**NON**'} |")

    orphelins = sorted(reels - utilises)
    if orphelins:
        alertes.append(f"outil(s) installe(s) mais attribue(s) a aucun agent : {', '.join(orphelins)}")

    lignes += ["", "## Outils reellement installes et leur titulaire", "",
               "| outil | agents autorises | actions de la matrice |", "|---|---|---|"]
    for o in sorted(reels):
        titulaires = [e.cle for e in EXPERTISES.values() if o in e.outils]
        lignes.append(f"| `{o}` | {', '.join(titulaires) or '**personne**'} "
                      f"| {', '.join(NATURE_OUTILS[o])} |")

    lignes += ["", "## Verdict", ""]
    if alertes:
        lignes += [f"**{len(alertes)} incoherence(s)** :"] + [f"- {a}" for a in alertes]
    else:
        lignes.append("**Coherent** : chaque agent est documente, chaque outil cite existe, "
                      "chaque outil installe a un titulaire, chaque action sensible est bien "
                      "classee en validation humaine.")
    return "\n".join(lignes)


def runs(limite: int = 10) -> str:
    traces = sorted((ROOT / "out").glob("*/trace.json"), key=lambda p: p.stat().st_mtime,
                    reverse=True)[:limite]
    if not traces:
        return "Aucune mission enregistree pour l'instant."
    lignes = ["# Dernieres missions", "",
              "| dossier | demande | duree | volets | rapport |", "|---|---|---|---|---|"]
    for t in traces:
        d = _charge_json(t) or {}
        etapes = d.get("etapes") or []
        volets = [e["acteur"] for e in etapes if e.get("etape") in ("DELEGATION", "EN PROPRE")
                  and e.get("detail", "").startswith(("completed", "traite"))]
        manquants = [e["acteur"] for e in etapes if e.get("etape") == "DELEGATION"
                     and not e.get("detail", "").startswith("completed")]
        demande = (d.get("demande") or "")[:70].replace("\n", " ")
        lignes.append(f"| {t.parent.name} | {demande}… | {d.get('duree_s', '?')} s "
                      f"| {', '.join(volets) or '-'}"
                      + (f" (non traites : {', '.join(manquants)})" if manquants else "")
                      + f" | {t.parent.name}/rapport.md |")
    return "\n".join(lignes)


def validations() -> str:
    from validation import en_attente
    demandes = en_attente()
    if not demandes:
        return "Aucune action sensible en attente de validation."
    lignes = [f"# {len(demandes)} action(s) sensible(s) en attente", ""]
    for d in demandes:
        lignes += [f"- **{d['id']}** — `{d['action']}` demandee par {d['agent']} le {d['demande_le']}",
                   f"  - motif : {d['motif'][:200]}",
                   f"  - approuver : `python validation.py --approuver {d['id']}`"]
    return "\n".join(lignes)


def journal(limite: int = 20) -> str:
    f = ROOT / "out" / "supervision.jsonl"
    if not f.exists():
        return "Aucune ligne de supervision (out/supervision.jsonl)."
    lignes = f.read_text(encoding="utf-8").splitlines()[-limite:]
    sortie = ["# Journal de supervision", ""]
    for ligne in lignes:
        try:
            e = json.loads(ligne)
        except ValueError:
            continue
        sortie.append(f"- {e.get('ts', '?')} · {e.get('demande', '')[:60]}… · "
                      f"{e.get('duree_s', '?')} s · agents : {', '.join(e.get('agents') or [])} "
                      f"· validations en attente : {e.get('validations_en_attente', 0)}")
    return "\n".join(sortie)


def main() -> int:
    p = argparse.ArgumentParser(description="Supervision AGROGUIDCI")
    p.add_argument("--etat", action="store_true")
    p.add_argument("--charte", action="store_true")
    p.add_argument("--coherence", action="store_true")
    p.add_argument("--runs", type=int, nargs="?", const=10)
    p.add_argument("--validations", action="store_true")
    p.add_argument("--journal", type=int, nargs="?", const=20)
    p.add_argument("--tout", action="store_true")
    args = p.parse_args()

    blocs: list[str] = []
    if args.tout or args.etat:
        blocs.append(etat())
    if args.tout or args.charte:
        blocs.append(charte())
    if args.tout or args.coherence:
        blocs.append(coherence())
    if args.runs is not None:
        blocs.append(runs(args.runs))
    if args.tout or args.validations:
        blocs.append(validations())
    if args.journal is not None:
        blocs.append(journal(args.journal))
    if not blocs:
        p.print_help()
        return 0
    print("\n\n".join(blocs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

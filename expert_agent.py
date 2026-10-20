"""
expert_agent.py — agent expert generique d'AGROGUIDCI.

Un seul executant pour les trois expertises (`experts.py`) : il s'enrole aupres
de l'orchestrateur, maintient sa presence, retire les taches de sa competence,
les execute avec le modele de langage + sa base de connaissances, puis remonte un
resultat structure et trace (journal local JSONL).

    python expert_agent.py --expert agronomie            # boucle de travail
    python expert_agent.py --expert production_animale --once
    python expert_agent.py --expert techniques_agricoles --question "..."   # test direct
    python expert_agent.py --expert agronomie enroll|whoami|taches

Variables : AGRO_ORCH, HEARTBEAT_MS, AGRO_LLM_MODEL, DEEPSEEK_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agrokit import (ROOT, BaseConnaissances, ErreurLLM, LLM, Orchestrateur,  # noqa: E402
                     dire, horodate, sha256)
from experts import EXPERTISES, Expertise  # noqa: E402
from permissions import intentions_interdites, verifier as verifier_permission  # noqa: E402

JOURNAL = Path(os.environ.get("AGRO_JOURNAL")
              or (ROOT / "out" / "journal-experts.jsonl"))   # surchargeable pour les tests


# --------------------------------------------------------------------------- execution d'une tache
def executer(expert: Expertise, instruction: str, llm: LLM, kb: BaseConnaissances,
             contexte: str = "", action: str | None = None) -> dict:
    """Produit la reponse de l'expert pour une instruction donnee (trace incluse)."""
    debut = time.time()
    manquants = kb.manquants()
    question = instruction.strip()
    if contexte.strip():
        question = f"{question}\n\nCONTEXTE CLARIFIE PAR LE COORDINATEUR\n{contexte.strip()}"

    # Outils : les donnees reelles sont collectees AVANT tout raisonnement, et
    # chaque usage passe d'abord par la matrice de permissions (LAB 09).
    donnees_outils: list[str] = []
    notes_outils: list[str] = []          # outils sautes : aucune donnee produite
    etats_outils: dict[str, tuple[str, int, str]] = {}
    dossier_outils = ROOT / "out" / "outils" / f"{time.strftime('%Y%m%d-%H%M%S')}-{expert.cle}"
    if getattr(expert, "outils", ()):
        dossier_outils.mkdir(parents=True, exist_ok=True)
        from outils import MARQUEUR_ECHEC, MARQUEUR_INSUFFISANT, executer_outil, pertinent
        for nom_outil in expert.outils:
            perm = verifier_permission(nom_outil)
            if perm["mode"] == "interdit":
                bloc = (f"ECHEC_PERMISSION: {nom_outil} — {perm['regle']}\n"
                        f"### Outil « {nom_outil} » — REFUSE PAR LA MATRICE DE PERMISSIONS\n"
                        f"{perm['regle']}\nAucune donnee produite, aucune tentative de contournement.")
                donnees_outils.append(f"#### Outil « {nom_outil} »\n{bloc}")
                etats_outils[nom_outil] = ("ARRETEE_PERMISSION", 0, "0")
                dire("PERMISSION", f"{nom_outil} refuse par la matrice de permissions")
                continue
            # Precondition : ne pas lancer un outil qui ne peut rien produire ici
            # (ni document cite, ni localite, ni montant...). Etat journalise.
            ok, motif = pertinent(nom_outil, instruction, contexte)
            if not ok:
                etats_outils[nom_outil] = ("NON_PERTINENT", 0, "-")
                notes_outils.append(f"- `{nom_outil}` : non execute — {motif}.")
                dire("OUTIL", f"{nom_outil} — non pertinent ({motif})")
                continue
            dire("OUTIL", f"{nom_outil} en execution (permission: {perm['mode']})...")
            bloc = executer_outil(nom_outil, instruction, contexte, dossier_outils)
            donnees_outils.append(f"#### Outil « {nom_outil} »\n{bloc}")
            code = "-"
            if MARQUEUR_ECHEC in bloc:
                mc = re.search(r"HTTP (\d{3})", bloc)
                code = mc.group(1) if mc else "0"
            etat = ("ECHEC_OUTIL" if MARQUEUR_ECHEC in bloc
                    else "DONNEE_INSUFFISANTE" if MARQUEUR_INSUFFISANT in bloc else "OK")
            etats_outils[nom_outil] = (etat, 1, code)
            dire("OUTIL", f"{nom_outil} — {etat} — {len(bloc)} car.")

    # Permissions : une demande d'action externe ne doit jamais etre executee.
    interdits = intentions_interdites(f"{instruction}\n{contexte}")

    messages = [
        {"role": "system", "content": expert.prompt},
        {"role": "system", "content":
            "BASE DE CONNAISSANCES D'AGROGUIDCI (source de reference de cet expert) :\n\n"
            + (kb.texte() or "(base vide)")},
    ]
    if interdits:
        refus = "\n".join(f"- {i['libelle']} (action `{i['action']}`, mode **{i['mode']}**) : "
                          f"{i['regle']}" for i in interdits)
        messages.append({"role": "system", "content":
            "PERMISSIONS AGROGUIDCI — ACTIONS REFUSEES (matrice PARTIE C) :\n" + refus +
            "\n\nTu N'EXECUTES PAS ces actions et tu ne diras jamais qu'elles ont ete faites. "
            "Tu fournis ce qui est autorise (brouillon a recopier, elements de dossier, plan) et "
            "tu indiques explicitement que l'action externe reste a la charge du producteur, "
            "apres validation humaine."})
        dire("PERMISSION", f"{len(interdits)} action(s) interdite(s) detectee(s) : "
                           f"{', '.join(i['action'] for i in interdits)}")

    if donnees_outils:
        messages.append({"role": "user", "content":
            "DONNEES REELLES PRODUITES PAR TES OUTILS (reprends-les TELLES QUELLES : ne "
            "recalcule pas, n'arrondis pas, ne complete jamais une valeur manquante ; cite "
            "la source et la date de releve ; si un outil a echoue, ecris-le) :\n\n"
            + "\n\n".join(donnees_outils)})
    if notes_outils:
        messages.append({"role": "user", "content":
            "OUTILS NON EXECUTES POUR CETTE DEMANDE (aucune donnee produite : ne rien "
            "en deduire, ne pas les citer comme source) :\n" + "\n".join(notes_outils)})
    messages.append({"role": "user", "content":
        f"DEMANDE A TRAITER ({expert.role}, capacite « {expert.capacite} »)\n{question}\n\n"
        "Reponds avec le format impose. Sois concret, prudent, et dis clairement ce qui "
        "doit etre verifie localement."})
    try:
        reponse = llm.chat(messages, temperature=0.15, max_tokens=9000)
        statut = "completed"
        erreur = None
        if llm.derniere_finish == "length":
            erreur = None
            statut = "completed"
            reponse += ("\n\n> Reponse interrompue par la limite de longueur du modele "
                        "(finish_reason=length) : ce volet est PARTIEL, a completer.")
    except ErreurLLM as e:
        # Aucune reponse inventee : on remonte l'echec avec sa cause exacte.
        statut, erreur = "failed", f"echec du modele de langage : {e}"
        reponse = ("## Reponse impossible\n\n"
                   f"L'expert « {expert.nom} » n'a pas pu raisonner : {e}\n\n"
                   "Aucune reponse n'est produite plutot qu'une reponse non verifiee.")
    duree = time.time() - debut

    pied = (f"\n\n---\n_expert : {expert.nom} ({expert.agent_id}) · capacite : {expert.capacite} · "
            f"modele : {llm.modele or 'n/a'} · base : "
            + ", ".join(f"{n} {v['sha256'][:12]}" for n, v in kb.empreintes.items())
            + (f" · base manquante : {', '.join(manquants)}" if manquants else "")
            + f" · duree : {duree:.1f}s_"
            + (f"\n<!-- outils_dir={dossier_outils} -->" if donnees_outils else "")
            + (f"\n<!-- outils_etat=" + ";".join(f"{k}:{v[0]}:{v[1]}:{v[2]}"
                                                 for k, v in etats_outils.items()) + " -->"
               if etats_outils else "")
            + (f"\n<!-- permissions_refusees=" + ";".join(i["action"] for i in interdits) + " -->"
               if interdits else ""))

    # Journal local : tout ce qui permet de rejouer et d'auditer cette reponse.
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "expert": expert.cle,
            "agent_id": expert.agent_id, "capacite": expert.capacite, "action": action,
            "modele": llm.modele, "duree_s": round(duree, 2),
            "empreintes_base": kb.empreintes, "instruction": instruction,
            "contexte": contexte, "instruction_sha256": sha256(question),
            "outils": list(getattr(expert, "outils", ())),
            "outils_etat": {k: {"etat": v[0], "tentatives": v[1], "code": v[2]}
                            for k, v in etats_outils.items()},
            "permissions_refusees": [i["action"] for i in interdits],
            "donnees_outils_sha256": [sha256(d) for d in donnees_outils],
            "dossier_outils": str(dossier_outils) if donnees_outils else None,
            "statut": statut, "erreur": erreur,
        }, ensure_ascii=False) + "\n")

    return {"status": statut, "action": action or "expertise", "error": erreur,
            "result": reponse + pied, "duree_s": round(duree, 2),
            "modele": llm.modele, "empreintes": kb.empreintes}


def executer_tache(expert: Expertise, tache: dict, llm: LLM, kb: BaseConnaissances) -> dict:
    instruction = tache.get("instruction") or tache.get("prompt") or ""
    # Le coordinateur peut passer un contexte clarifie en tete de l'instruction.
    contexte = ""
    marqueur = "\n\nCONTEXTE CLARIFIE PAR LE COORDINATEUR\n"
    if marqueur in instruction:
        instruction, contexte = instruction.split(marqueur, 1)
    return executer(expert, instruction, llm, kb, contexte=contexte, action=tache.get("action"))


# --------------------------------------------------------------------------- boucle d'agent
def charger_jeton(expert: Expertise, orch: Orchestrateur) -> str:
    f = ROOT / f".agent-token-{expert.cle}.json"
    if f.exists():
        try:
            jeton = json.loads(f.read_text(encoding="utf-8")).get("agent_token")
            if jeton:
                return jeton
        except (ValueError, OSError):
            pass
    identite = {**expert.identite, "capabilities": [expert.capacite]}
    jeton = orch.enroler(identite)
    f.write_text(json.dumps({"enrolled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "agent_token": jeton, "agent_id": expert.agent_id},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    dire("ENROLL", f"{expert.nom} inscrit (jeton dans {f.name})")
    return jeton


def boucle(expert: Expertise, orch: Orchestrateur, llm: LLM, kb: BaseConnaissances,
           periode_ms: int, une_fois: bool = False) -> int:
    jeton = charger_jeton(expert, orch)
    orch.register(expert.agent_id, expert.nom, [expert.capacite],
                  expert.identite["endpoint"], role=expert.role)
    orch.battement(jeton, [expert.capacite])
    dire("EN LIGNE", f"{expert.nom} — capacite « {expert.capacite} » — "
                     f"base {kb.volume} car. — modele {llm.modele or 'a resoudre'} — {orch.base}")
    en_cours = threading.Lock()

    def tick() -> None:
        if en_cours.locked():
            return                      # le tick precedent n'est pas fini : on ne double pas
        with en_cours:
            orch.register(expert.agent_id, expert.nom, [expert.capacite],
                          expert.identite["endpoint"], role=expert.role)
            orch.battement(jeton, [expert.capacite])
            for tache in orch.taches(jeton):
                dire("TACHE", f"{tache['task_id']} capacite={tache['capability']} "
                              f"action={tache.get('action') or '(expertise)'}")
                resultat = executer_tache(expert, tache, llm, kb)
                ok = orch.remonter(jeton, tache["task_id"], resultat["status"],
                                   resultat=resultat.get("result"), erreur=resultat.get("error"))
                dire("RESULTAT", f"{tache['task_id']} {resultat['status']} "
                                 f"({resultat['duree_s']}s) — {'remonte' if ok else 'REFUSÉ par l orchestrateur'}")

    tick()
    if une_fois:
        return 0
    while True:
        time.sleep(max(periode_ms, 3000) / 1000.0)
        tick()


def main() -> int:
    p = argparse.ArgumentParser(description="Agent expert AGROGUIDCI")
    p.add_argument("--expert", required=True, choices=sorted(EXPERTISES))
    p.add_argument("--once", action="store_true", help="un seul cycle puis sortie")
    p.add_argument("--question", help="test direct : repond sans passer par l'orchestrateur")
    p.add_argument("--contexte", default="", help="contexte clarifie a joindre (test direct)")
    p.add_argument("--orchestrateur", default=None)
    p.add_argument("commande", nargs="?", default="work", choices=["work", "taches", "whoami", "enroll"])
    args = p.parse_args()

    expert = EXPERTISES[args.expert]
    orch = Orchestrateur(args.orchestrateur)
    kb = BaseConnaissances(expert.fichiers).charger()
    llm = LLM()

    if not orch.health():
        dire("ERREUR", f"orchestrateur injoignable sur {orch.base} — démarre-le d'abord "
                       "(python demarrer_agroguidci.py)")
        return 2

    if args.question:
        llm.resoudre_modele()
        r = executer(expert, args.question, llm, kb, contexte=args.contexte)
        print(r["result"])
        return 0 if r["status"] == "completed" else 1

    if kb.manquants():
        dire("ATTENTION", f"base de connaissances incomplete : {', '.join(kb.manquants())}")

    if args.commande == "enroll":
        charger_jeton(expert, orch)
        return 0
    if args.commande == "whoami":
        import urllib.request
        jeton = charger_jeton(expert, orch)
        req = urllib.request.Request(f"{orch.base}/api/v1/agents/me",
                                     headers={"Authorization": f"Bearer {jeton}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            print(r.read().decode("utf-8"))
        return 0
    if args.commande == "taches":
        print(json.dumps(orch.taches(charger_jeton(expert, orch)), ensure_ascii=False, indent=2))
        return 0

    return boucle(expert, orch, llm, kb,
                  int(__import__("os").environ.get("HEARTBEAT_MS", "10000")), args.once)


if __name__ == "__main__":
    raise SystemExit(main())

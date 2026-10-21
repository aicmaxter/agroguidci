"""
coordinateur.py — AGROGUIDCI : l'AGENT PRINCIPAL (Agent Agronome Expert).

C'est le cerveau operationnel du systeme. Il n'est pas un expert de plus : il
CLARIFIE la demande, SELECTIONNE les sous-agents utiles a la mission, les
COORDONNE (delegation au reseau d'agents de l'orchestrateur), traite LUI-MEME le
volet agronomique (il est l'agronome de reference) et rend une reponse unique,
prudente et TRACABLE.

    python coordinateur.py --demande "J'ai 2 ha a Bouake, que cultiver ?"
    python coordinateur.py --demande "..." --domaines agronomie,production_animale
    python coordinateur.py work            # sert « coordination_agroguidci » et « agronomie »
    python coordinateur.py --etat          # etat du reseau d'agents

Chaque mission ecrit un dossier dans out/<horodatage>/ contenant :
    rapport.md          la reponse remise au producteur
    trace.json          le journal complet et auditable (qui, quand, avec quoi)
    clarification.json  la lecture de la demande et les hypotheses retenues
    experts/*.md        les reponses brutes de chaque agent mobilise
    outils/*/           les donnees brutes produites par les outils des agents

Supervision : chaque mission ajoute une ligne a out/supervision.jsonl (voir
`python supervision.py --tout`), et les actions sensibles passent par
`python validation.py` (validation humaine).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agrokit import (ROOT, LLM, SERVICE, BaseConnaissances, ErreurLLM, Orchestrateur,  # noqa: E402
                     Trace, dire, dossier_sortie, horodate)
from confidentialite import masquer_champs  # noqa: E402  minimisation des journaux
from expert_agent import executer as executer_agent  # noqa: E402
from experts import EXPERTISES, PRINCIPAL, SOUS_AGENTS, Expertise, par_capacite  # noqa: E402
from mission import JournalMission  # noqa: E402
from permissions import intentions_interdites, rapport_matrice, verifier as verifier_permission  # noqa: E402
import verification as verif  # noqa: E402

AGENT_ID = PRINCIPAL.agent_id            # l'agent principal EST l'Agent Agronome Expert
NOM = PRINCIPAL.nom
ROLE = PRINCIPAL.role                    # « agent_principal »
CAPACITE = "coordination_agroguidci"     # capacite de coordination (en plus de l'agronomie)
CAPACITES = list(PRINCIPAL.capacites)
VERSION = "1.1"
# Capacités réellement routables (les identifiants d'expertise ne sont pas des
# capacités : « recherche » est servi par la capacité « recherche_agricole »).
DOMAINES = sorted({e.capacite for e in EXPERTISES.values()})


def en_attente_validation() -> list[dict]:
    """Actions sensibles deposees et non encore tranchees par un humain."""
    try:
        from validation import en_attente
        return en_attente()
    except Exception:
        return []


FILIERES = ("cacao", "riz", "mais", "igname", "manioc", "maraich", "cafe", "anacarde",
            "palmier", "coton", "plantain", "banane", "arachide", "poulet", "volaille", "elevage",
            "porc", "bovin", "caprin", "ovin", "poisson", "tilapia", "clarias", "apiculture",
            "ananas", "hevea")


def mission_ciblable(demande: str) -> tuple[bool, list[str]]:
    """La mission peut-elle etre traitee sans precision supplementaire ?

    Sans localite ET sans filiere identifiable, aucune reponse ciblee n'est possible :
    le systeme doit demander ces precisions (etat EN_ATTENTE_INFORMATION).
    """
    from outils import extraire_localite
    from permissions import sans_accents
    t = sans_accents(demande)
    manques: list[str] = []
    if not extraire_localite(demande):
        manques.append("la localite (pour le climat, les sols et les filieres locales)")
    if not any(f in t for f in FILIERES):
        manques.append("la production visee (culture ou elevage)")
    return (not manques), manques

PROMPT_CLARIFICATION = """Tu es AGROGUIDCI, expert coordinateur d'accompagnement agricole en
Cote d'Ivoire. Ta premiere tache est de LIRE une demande de producteur avant toute
recommandation : reformuler le besoin reel, reperer la zone et le systeme de
production, et surtout identifier ce qui manque.

Tu ne reponds pas a la question technique ici. Tu produis uniquement l'analyse de
la demande, en JSON strict, avec exactement ces cles :
{
  "besoin_principal": "phrase courte : ce que le producteur cherche vraiment",
  "type_demande": "diagnostic|conseil_technique|choix_de_speculation|elevage|projet|mixte|autre",
  "zone_probable": "zone ou region si elle est identifiable, sinon 'non precisee'",
  "systeme_probable": "ex: petite exploitation familiale 1-3 ha, elevage peri-urbain, bas-fond rizicole...",
  "hypotheses": ["hypothese indispensable que tu retiens faute d'information"],
  "informations_manquantes": ["information qui manque et qui changerait la reponse"],
  "questions_a_poser": ["question precise a poser au producteur, 3 a 6, ordonnee par importance"],
  "capacites_a_mobiliser": ["agronomie", "techniques_agricoles", "production_animale", "recherche_agricole", "analyse_donnees", "relation_producteur", "automatisation"],
  "capacites_hors_reseau": ["besoin identifie mais hors du perimetre des agents (credit, foncier, marche, juridique, veterinaire de terrain...)"],
  "prudence": ["point de vigilance deja identifiable (sante, environnement, securite, delais)"],
  "complexite": "simple|moyenne|elevee"
}

Choisis les capacites dans cette liste, et seulement celles que la demande justifie :
- "agronomie" : sols, zones agroecologiques, choix des cultures, varietes, fertilite, associations.
- "techniques_agricoles" : comment faire — preparation, semis, densites, entretiens, fertilisation, eau, protection des cultures, post-recolte.
- "production_animale" : elevage (volaille, porc, bovins, ovins/caprins, pisciculture), alimentation, biosecurite, conduite de l'atelier.
- "recherche_agricole" : quand il faut des DONNEES REELLES sur la zone ou des sources — pluie et climat de la localite, deficit hydrique, prevision, contexte documentaire, indicateurs du pays.
- "analyse_donnees" : quand la demande contient des CHIFFRES a traiter — marge, rentabilite, seuil, tableau de donnees, statistiques.
- "relation_producteur" : quand il faut qualifier le dossier, tenir le suivi, rediger un message court et clair pour le producteur, repondre a une reclamation.
- "automatisation" : quand il faut des ECHEANCES — calendrier, rappels, relances, tache planifiee, suivi dans le temps.

Regles : ne mobilise une capacite que si la demande la justifie reellement ; ne mets
pas les trois capacites metier par reflexe. Une question mixte mobilise plusieurs
capacites (par exemple climat + cultures + calcul de marge + rappels). Le veterinaire,
le credit, le foncier et les prix de marche n'appartiennent a personne : ils vont dans
capacites_hors_reseau. N'invente aucune information : ce qui manque va dans
informations_manquantes. Reponds en francais."""

PROMPT_SYNTHESE = """Tu es AGROGUIDCI, expert coordinateur d'accompagnement agricole en Cote
d'Ivoire. Tu recois la demande d'un producteur, l'analyse de cette demande, et les
reponses de tes sous-agents (Techniques Agricoles, Production Animale, Recherche
Agricole, Analyse de Donnees, Relation Producteurs et Accompagnement,
Automatisation) et ton propre volet agronomique. Tu produis LA reponse unique et
coherente remise au producteur.

Regles absolues :
1. N'ajoute AUCUN fait, chiffre, prix, produit ou variete qui ne figure pas dans
   les reponses des experts. Tu organises, tu hierarchises, tu relies — tu
   n'inventes pas.
2. Attribue les recommandations a leur auteur : "en tant qu'agronome je retiens ...",
   "le sous-agent Techniques Agricoles propose ...", "l'analyste a calcule ...".
3. Si deux experts divergent, dis-le explicitement et explique l'arbitrage que tu
   retiens, avec le critere utilise.
4. Conserve les avertissements de securite (sante animale, pesticides, zoonoses,
   environnement) et les renvois a l'echelon local (ANADER, CNRA, MINADER, MIRAH,
   veterinaire/mandataire sanitaire, cooperative).
5. Termine par ce qui reste a confirmer par le producteur : hypotheses retenues et
   questions a poser.
6. Jamais de dosage de pesticide ni de prescription veterinaire : tu relaies
   seulement le principe et le renvoi au professionnel.
7. Si un volet n'a pas pu etre traite (expert indisponible), tu l'ecris noir sur
   blanc au lieu de compenser.

Format markdown attendu, en francais, 700 a 1200 mots, sections exactement :
## Ce que je comprends de votre demande
## Plan d'action coordonne
(etapes ordonnees, chacune avec : quoi, quand, auteur de la recommandation)
## Chiffres et ordres de grandeur a retenir
(tableau : donnee | valeur | statut FAIT / A CONFIRMER | source expert)
## Ce qui reste a verifier avant d'agir
## Points de vigilance (sante, environnement, securite)
## Questions a me transmettre pour affiner
## Coordination des experts
(un paragraphe : qui a ete consulte, sur quel volet, avec quel apport)"""


SECTIONS_ATTENDUES = ("ce que je comprends", "plan d'action", "chiffres et ordres de grandeur",
                      "ce qui reste a verifier", "points de vigilance", "questions a me transmettre",
                      "coordination des experts")


def sans_accents(texte: str) -> str:
    table = str.maketrans("àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ'", "aaaeeeeiioouuucAAAEEEEIIOOUUUC ")
    return (texte or "").lower().translate(table)


SECTIONS_NORM = tuple(sans_accents(s) for s in SECTIONS_ATTENDUES)


def sections_manquantes(texte: str) -> list[str]:
    """Sections attendues absentes de la synthese (comparaison sans accents ni apostrophes)."""
    norm = sans_accents(texte)
    return [orig for orig, n in zip(SECTIONS_ATTENDUES, SECTIONS_NORM) if n not in norm]


# --------------------------------------------------------------------------- etat du reseau
def etat_reseau(orch: Orchestrateur) -> dict:
    try:
        agents = orch.agents()
    except Exception as e:  # orchestrateur injoignable
        return {"orchestrateur": orch.base, "joignable": False, "erreur": str(e), "agents": []}
    utiles = [a for a in agents if a.get("capabilities") and
              (set(a["capabilities"]) & set(DOMAINES) or "coordination" in " ".join(a["capabilities"]))]
    return {"orchestrateur": orch.base, "joignable": True,
            "agents": [{"name": a.get("name"), "agent_id": a.get("agent_id"),
                        "capabilities": a.get("capabilities"), "status": a.get("status"),
                        "last_seen_age_s": a.get("last_seen_age_s"), "protocol": a.get("protocol")}
                       for a in utiles]}


# --------------------------------------------------------------------------- moteur
class Coordonnateur:
    """Le pipeline complet : clarifier -> selectionner -> coordonner -> repondre -> tracer."""

    def __init__(self, orch: Orchestrateur | None = None, llm: LLM | None = None,
                 timeout_delegation: float = 420.0) -> None:
        self.orch = orch or Orchestrateur()
        self.llm = llm or LLM()
        self.timeout = timeout_delegation

    # -- 1. presence ------------------------------------------------------
    def presence(self) -> None:
        """L'agent principal est un agent du reseau (visible, journalise)."""
        try:
            je = {"agent_id": AGENT_ID, "name": NOM, "role": ROLE, "runtime": "python",
                  "endpoint": PRINCIPAL.identite["endpoint"], "capabilities": CAPACITES}
            self.orch.register(AGENT_ID, NOM, je["capabilities"], je["endpoint"], role=ROLE)
            jeton = self._jeton()
            self.orch.battement(jeton, je["capabilities"])
        except Exception as e:
            dire("PRESENCE", f"presence non annoncee : {e}")

    def _jeton(self) -> str:
        f = Path(__file__).resolve().parent / f".agent-token-{PRINCIPAL.cle}.json"
        if f.exists():
            try:
                j = json.loads(f.read_text(encoding="utf-8")).get("agent_token")
                if j:
                    return j
            except (ValueError, OSError):
                pass
        jeton = self.orch.enroler({"agent_id": AGENT_ID, "name": NOM, "role": ROLE,
                                   "runtime": "python",
                                   "endpoint": PRINCIPAL.identite["endpoint"],
                                   "capabilities": CAPACITES})
        f.write_text(json.dumps({"enrolled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "agent_token": jeton, "agent_id": AGENT_ID},
                                ensure_ascii=False, indent=2), encoding="utf-8")
        return jeton

    # -- 2. clarification -------------------------------------------------
    def clarifier(self, demande: str, trace: Trace) -> dict:
        base = {
            "besoin_principal": demande.strip(), "type_demande": "autre",
            "zone_probable": "non precisee", "systeme_probable": "non precise",
            "hypotheses": [], "informations_manquantes": [], "questions_a_poser": [],
            "capacites_a_mobiliser": [], "capacites_hors_reseau": [], "prudence": [],
            "complexite": "moyenne", "methode": "llm",
        }
        try:
            analyse = self.llm.chat_json([
                {"role": "system", "content": PROMPT_CLARIFICATION},
                {"role": "user", "content": f"DEMANDE DU PRODUCTEUR\n{demande}"},
            ], temperature=0.1, max_tokens=4000)
            base.update({k: analyse.get(k, base[k]) for k in base if k in analyse})
            base["methode"] = "llm"
        except (ErreurLLM, ValueError) as e:
            # Repli explicite : analyse par mots-cles, annoncee comme telle.
            base["methode"] = "mots_cles"
            base["erreur_llm"] = str(e)
            scores = {cle: sum(1 for m in e_.mots_cles if m in demande.lower())
                      for cle, e_ in EXPERTISES.items()}
            base["capacites_a_mobiliser"] = [c for c, s in scores.items() if s > 0] or DOMAINES
            base["scores_mots_cles"] = scores
            base["informations_manquantes"] = ["zone / localite", "superficie disponible",
                                               "moyens (main d'oeuvre, budget)", "objectif de production"]
            base["questions_a_poser"] = [f"Ou se trouve exactement votre parcelle ({m}) ?"
                                         for m in base["informations_manquantes"]]
        trace.ajoute("CLARIFICATION", "AGROGUIDCI", f"methode={base['methode']} · "
                     f"besoin={base['besoin_principal'][:80]}", clarification=base)
        return base

    def selectionner(self, demande: str, clarification: dict, trace: Trace,
                     domaines_forces: list[str] | None = None) -> list[Expertise]:
        """Selection des competences : la decision est explicite et justifiee."""
        if domaines_forces:
            choisis, inconnus = [], []
            for c in domaines_forces:
                if c in EXPERTISES:                       # cle d'agent
                    choisis.append(c)
                elif par_capacite(c):                     # ou nom de capacite annoncee
                    choisis.append(par_capacite(c).cle)
                else:
                    inconnus.append(c)
            motif = "imposes en ligne de commande"
            if inconnus:
                dire("SELECTION", f"capacite(s) inconnue(s) ignoree(s) : {', '.join(inconnus)}")
                trace.ajoute("SELECTION", "AGROGUIDCI",
                             f"capacite(s) inconnue(s) ignoree(s) : {', '.join(inconnus)}")
        else:
            demande_caps = []
            for c in (clarification.get("capacites_a_mobiliser") or []):
                if c in EXPERTISES:                 # cle d'agent
                    demande_caps.append(c)
                elif par_capacite(c):               # nom de capacite annoncee par le coordinateur LLM
                    demande_caps.append(par_capacite(c).cle)
            if demande_caps:
                choisis, motif = demande_caps, "proposes par la clarification"
            else:
                scores = {cle: sum(1 for m in e.mots_cles if m in demande.lower())
                          for cle, e in EXPERTISES.items()}
                choisis = [c for c, s in scores.items() if s > 0] or DOMAINES
                motif = "mots-cles" if any(scores.values()) else "aucun domaine identifie : consultation large"
        experts = [EXPERTISES[c] for c in choisis]
        trace.ajoute("SELECTION", "AGROGUIDCI",
                     f"{len(experts)} competence(s) : " + ", ".join(e.cle for e in experts) + f" ({motif})",
                     capacites=[e.capacite for e in experts], motif=motif)
        return experts

    # -- 3. coordination --------------------------------------------------
    def coordonner(self, demande: str, experts: list[Expertise], clarification: dict,
                   trace: Trace) -> dict[str, dict]:
        contexte = self.contexte_consigne(clarification)
        instruction = (f"{demande}\n\nCONTEXTE CLARIFIE PAR LE COORDONNATEUR\n{contexte}")
        resultats: dict[str, dict] = {}

        def un(expert: Expertise) -> tuple[str, dict]:
            debut = time.time()
            dire("DELEGATION", f"capacite « {expert.capacite} » → orchestrateur")
            try:
                rep = self.orch.deleguer(expert.capacite, instruction, action="expertise",
                                         timeout=self.timeout)
            except Exception as e:
                rep = {"status": "error", "error": str(e)}
            rep["duree_s"] = round(time.time() - debut, 2)
            return expert.capacite, rep

        with ThreadPoolExecutor(max_workers=max(1, len(experts))) as pool:
            for capacite, rep in pool.map(un, experts):
                resultats[capacite] = rep

        for capacite, rep in resultats.items():
            statut = rep.get("status")
            detail = (f"{statut} · agent={rep.get('agent_name') or rep.get('agent_id') or 'n/a'} · "
                      f"{rep.get('duree_s')}s · {len(rep.get('result') or '')} car.")
            trace.ajoute("DELEGATION", capacite, detail, task_id=rep.get("task_id"),
                         agent_id=rep.get("agent_id"), agent_name=rep.get("agent_name"),
                         statut=statut, duree_s=rep.get("duree_s"),
                         erreur=rep.get("error"))
        return resultats

    @staticmethod
    def contexte_consigne(clarification: dict) -> str:
        lignes = [
            f"- besoin principal retenu : {clarification.get('besoin_principal')}",
            f"- zone : {clarification.get('zone_probable')}",
            f"- systeme de production suppose : {clarification.get('systeme_probable')}",
            f"- hypotheses retenues faute d'information : {'; '.join(clarification.get('hypotheses') or []) or 'aucune'}",
            f"- informations manquantes : {'; '.join(clarification.get('informations_manquantes') or []) or 'aucune'}",
            f"- vigilance deja identifiee : {'; '.join(clarification.get('prudence') or []) or 'aucune'}",
        ]
        return "\n".join(lignes)

    # -- 3bis. volet traite en propre par l'agent principal ---------------
    def volet_en_propre(self, demande: str, clarification: dict, trace: Trace) -> dict:
        """L'agent principal traite lui-meme le volet agronomique : il EST l'agronome."""
        dire("EN PROPRE", f"« {PRINCIPAL.capacite} » traite par l'agent principal (sans delegation)")
        kb = BaseConnaissances(PRINCIPAL.fichiers).charger()
        contexte = self.contexte_consigne(clarification)
        rep = executer_agent(PRINCIPAL, demande, self.llm, kb, contexte=contexte, action="expertise")
        rep |= {"task_id": None, "agent_id": PRINCIPAL.agent_id, "agent_name": PRINCIPAL.nom,
                "status": rep.get("status", "completed")}
        trace.ajoute("EN PROPRE", PRINCIPAL.capacite,
                     f"traite par l'agent principal ({rep.get('duree_s')}s, "
                     f"{len(rep.get('result') or '')} car.)",
                     agent_id=PRINCIPAL.agent_id, statut=rep.get("status"),
                     duree_s=rep.get("duree_s"))
        return rep

    # -- 4. synthese ------------------------------------------------------
    def synthetiser(self, demande: str, clarification: dict, resultats: dict[str, dict],
                    trace: Trace) -> dict:
        morceaux = []
        for capacite, rep in resultats.items():
            expert = par_capacite(capacite)
            nom = expert.nom if expert else capacite
            if rep.get("status") == "completed" and rep.get("result"):
                morceaux.append(f"### REPONSE DE {nom.upper()} (capacite {capacite})\n{rep['result']}")
            else:
                morceaux.append(f"### VOLET {capacite.upper()} : NON TRAITE\n"
                                f"statut={rep.get('status')} · raison={rep.get('error')}")
        # Cadrage explicite : le modele ne doit pas confondre un volet NON consulte
        # (non retenu par la selection) avec un volet consulte en echec.
        consultees = list(resultats)
        en_echec = [c for c, r in resultats.items() if r.get("status") != "completed"]
        traitees = [c for c in consultees if c not in en_echec]
        toutes = sorted({e.capacite for e in EXPERTISES.values()})
        non_consultees = [c for c in toutes if c not in consultees]
        cadrage = ("\n\nCADRAGE DE LA COORDINATION (a respecter dans la section "
                   "« Coordination des experts »)\n"
                   f"- Volets consultes et traites : {', '.join(traitees) or 'aucun'}\n"
                   f"- Volets consultes en echec : {', '.join(en_echec) or 'aucun'}\n"
                   f"- Volets NON consultes (non retenus pour cette demande : ils ne sont PAS "
                   f"defaillants) : {', '.join(non_consultees) or 'aucun'}\n"
                   "Ne presente jamais un volet non consulte comme un volet en echec ou en attente "
                   "de reponse, et n'attribue a un volet non consulte aucune analyse.")
        dossier = ("DEMANDE DU PRODUCTEUR\n" + demande
                   + "\n\nANALYSE DE LA DEMANDE PAR LE COORDONNATEUR\n"
                   + json.dumps(clarification, ensure_ascii=False, indent=2)
                   + "\n\nREPONSES DES EXPERTS\n" + "\n\n".join(morceaux)
                   + cadrage
                   + "\n\nProduis maintenant la reponse unique remise au producteur, "
                     "avec exactement les sections demandees, et mentionne explicitement "
                     "tout volet consulte en echec.")

        def appel(complement: str = "", max_tokens: int = 14000) -> str:
            return self.llm.chat([
                {"role": "system", "content": PROMPT_SYNTHESE},
                {"role": "user", "content": dossier + complement},
            ], temperature=0.2, max_tokens=max_tokens)

        try:
            texte = appel()
            avis: list[str] = []
            fini = self.llm.derniere_finish
            manquantes = sections_manquantes(texte)
            if fini == "length" or manquantes:
                # Le modele s'est arrete en route (limite de jetons ou reponse courte) :
                # une relance explicite avant de livrer une reponse partielle.
                trace.ajoute("SYNTHESE", "AGROGUIDCI",
                             f"reponse incomplete (finish={fini}, sections manquantes={manquantes}) "
                             "→ relance unique")
                try:
                    texte = appel("\n\nATTENTION : la reponse precedente s'est interrompue avant la fin. "
                                  "Produis la reponse COMPLETE et va jusqu'a la derniere section "
                                  "« Coordination des experts ». Resserre chaque section si necessaire, "
                                  "mais ne t'arrete plus en route.", max_tokens=18000)
                except ErreurLLM:
                    pass
                fini = self.llm.derniere_finish
                manquantes = sections_manquantes(texte)
            if fini == "length":
                avis.append("la reponse du modele a de nouveau ete coupee par la limite de longueur "
                            "(finish_reason=length) : lire aussi les volets experts bruts en annexe.")
            if manquantes:
                avis.append("sections non fournies par le modele : " + ", ".join(manquantes)
                            + " — ce qui a pu etre reconstitue par le coordinateur figure ci-dessous, "
                              "le reste est dans les volets bruts.")
            trace.ajoute("SYNTHESE", "AGROGUIDCI",
                         f"reponse produite ({len(texte)} car., finish={fini})",
                         modele=self.llm.modele, jetons=self.llm.statistiques["jetons"],
                         sections_manquantes=manquantes, avis=avis)
            return {"texte": texte, "avis": avis, "sections_manquantes": manquantes, "finish": fini}
        except ErreurLLM as e:
            # Pas de synthese inventee : on assemble les volets bruts et on le dit.
            trace.ajoute("SYNTHESE", "AGROGUIDCI", f"echec du modele : {e}")
            return {"texte": ("## Synthese indisponible\n\n"
                              f"Le modele de coordination n'a pas pu etre appele : {e}\n\n"
                              "Les volets experts bruts ci-dessous n'ont pas ete coordonnes ; "
                              "les lire separement et les faire valider localement.\n\n"
                              + "\n\n".join(morceaux)),
                    "avis": ["synthese non produite : " + str(e)],
                    "sections_manquantes": list(SECTIONS_ATTENDUES), "finish": None}

    # -- 5. rapport et trace ---------------------------------------------
    def rapport(self, demande: str, clarification: dict, resultats: dict[str, dict],
                synthese: dict, dossier: Path, trace: Trace, etiquette: str | None = None,
                journal: JournalMission | None = None, verification: dict | None = None,
                etat_final: str | None = None, permissions_refusees: list | None = None) -> Path:
        lignes = [
            "# AGROGUIDCI — Rapport d'accompagnement agricole",
            "",
            f"**Demande** : {demande}",
            "",
            f"**Date** : {time.strftime('%d/%m/%Y %H:%M')} · **Agent principal** : {NOM} ({AGENT_ID}) "
            f"· **version** : {VERSION}",
            f"**Consultation** : {', '.join(par_capacite(c).nom if par_capacite(c) else c for c in resultats)}",
            f"**État final** : **{etat_final or '—'}**"
            + (f" · mission `{journal.mission_id}`" if journal else ""),
            "",
            "---",
            "",
            synthese["texte"].strip(),
            "",
            *([f"> **Reserve du coordinateur** : {a}" for a in synthese.get("avis") or []]),
            "",
            "## Points de vigilance identifies au cadrage",
            "",
            *([f"- {p}" for p in (clarification.get("prudence") or [])]
              or ["- aucun signal particulier identifie au cadrage"]),
            "",
            "## Questions a me transmettre",
            "",
            *([f"{i}. {q}" for i, q in enumerate(clarification.get("questions_a_poser") or [], 1)]
              or ["- aucune question bloquante"]),
            "",
            *(["## Actions sensibles en attente de validation humaine",
               "",
               "> Ces actions n'ont pas ete executees : un operateur doit les approuver.",
               "",
               *[f"- `{d['id']}` — **{d['action']}** (deposee par {d['agent']}) : {d['motif'][:150]}"
                 f"  \n  approbation : `python validation.py --approuver {d['id']}`"
                 for d in en_attente_validation()],
               ""] if en_attente_validation() else []),
            "",
            *(["## Permissions (matrice PARTIE C)",
               "",
               "> Actions externes, persistantes, financières ou destructives : refusées ou "
               "soumises à validation humaine.",
               "",
               *[f"- refusée : **{i['libelle']}** (`{i['action']}`, mode {i['mode']}) — {i['regle']}"
                 for i in (permissions_refusees or [])],
               *["- aucune action interdite demandée dans cette mission." if not permissions_refusees else ""],
               "",
               "<details><summary>Matrice appliquée</summary>",
               "",
               rapport_matrice(),
               "",
               "</details>",
               ""] if etat_final else []),
            "",
            *(["## Vérifications effectuées (LAB 14)",
               "",
               verif.tableau(verification) if verification else "—",
               "",
               f"Détail : `{dossier / 'verification.md'}`",
               ""] if verification else []),
            "",
            *(["## Journal de mission (boucle d'autonomie)",
               "",
               "GOAL → PLAN → ACT → OBSERVE → DECIDE → ADAPT → VERIFY → CONTINUE/STOP/ESCALATE",
               "",
               journal.tableau() if journal else "—",
               "",
               f"Journal brut : `{journal.chemin if journal else '—'}`",
               ""] if journal else []),
            "",
            "---",
            "",
            "## Traçabilite de cette reponse",
            "",
            "| volet | agent | statut | tache | duree |",
            "|---|---|---|---|---|",
        ]
        for capacite, rep in resultats.items():
            expert = par_capacite(capacite)
            lignes.append(f"| {expert.cle if expert else capacite} | {rep.get('agent_name') or rep.get('agent_id') or '—'} "
                          f"| {rep.get('status')} | {rep.get('task_id') or 'en propre'} | {rep.get('duree_s')}s |")
        lignes += [
            "",
            f"- Duree totale du traitement : {trace.etapes[-1]['ecoule_s']:.1f}s",
            f"- Modele de langage : `{self.llm.modele or 'n/a'}` "
            f"({self.llm.statistiques['appels']} appels, {self.llm.statistiques['jetons']} jetons)",
            f"- Journal complet et auditable : `{dossier / 'trace.json'}`",
            f"- Reponses brutes des experts : `{dossier / 'experts'}`",
            "",
            "## Hypotheses retenues faute d'information",
            "",
        ]
        hyp = clarification.get("hypotheses") or []
        lignes += [f"- {h}" for h in hyp] or ["- aucune hypothese particuliere"]
        lignes += ["", "## Informations manquantes identifiees au cadrage", ""]
        manque = clarification.get("informations_manquantes") or []
        lignes += [f"- {m}" for m in manque] or ["- aucune"]
        lignes += ["", f"> Reponse produite par un systeme multi-agents coordonne par AGROGUIDCI "
                       f"({len(resultats)} agent(s) consulte(s) : "
                       f"{', '.join((par_capacite(c).nom if par_capacite(c) else c) for c in resultats)}). "
                       "Elle ne remplace ni le diagnostic de terrain de l'ANADER, ni l'avis d'un "
                       "veterinaire, ni une analyse de sol. Les chiffres indicatifs doivent etre "
                       "confirmes localement avant tout engagement financier.", ""]
        chemin = dossier / "rapport.md"
        chemin.write_text("\n".join(lignes), encoding="utf-8")
        return chemin

    # -- boucle d'autonomie : OBSERVE / DECIDE / ADAPT / VERIFY -------------
    @staticmethod
    def parser_marqueurs(texte: str) -> dict:
        """Lit les marqueurs laisses par l'agent : etat des outils et permissions refusees."""
        etats, permissions = {}, []
        m = re.search(r"<!--\s*outils_etat=([^>]+?)\s*-->", texte or "")
        if m:
            for item in m.group(1).split(";"):
                morceaux = item.split(":")
                if len(morceaux) >= 2:
                    etats[morceaux[0]] = {
                        "etat": morceaux[1],
                        "tentatives": int(morceaux[2]) if len(morceaux) > 2 and morceaux[2].isdigit() else 1,
                        "code": morceaux[3] if len(morceaux) > 3 else "-",
                    }
        m = re.search(r"<!--\s*permissions_refusees=([^>]+?)\s*-->", texte or "")
        if m:
            permissions = [p for p in m.group(1).split(";") if p]
        return {"outils": etats, "permissions_refusees": permissions}

    @staticmethod
    def observer(resultats: dict[str, dict], trace: Trace, journal: JournalMission,
                 attendus: dict[str, str]) -> dict[str, dict]:
        """OBSERVE : que dit reellement chaque volet (statut, outils, donnees) ?"""
        observations: dict[str, dict] = {}
        for capacite, rep in resultats.items():
            texte = rep.get("result") or ""
            marqueurs = Coordonnateur.parser_marqueurs(texte)
            echecs = [n for n, v in marqueurs["outils"].items() if v["etat"] == "ECHEC_OUTIL"]
            insuff = [n for n, v in marqueurs["outils"].items() if v["etat"] == "DONNEE_INSUFFISANTE"]
            # Erreur permanente (4xx hors 408/429) : inutile de relancer, on la declare
            # et on continue avec la donnee manquante (LAB 13).
            permanents = [n for n in echecs if marqueurs["outils"][n]["code"].startswith("4")
                          and marqueurs["outils"][n]["code"] not in ("408", "429")]
            transitoires = [n for n in echecs if n not in permanents]
            refus = marqueurs["permissions_refusees"]
            statut = ("OK" if rep.get("status") == "completed" and not echecs and not insuff
                      else "ECHEC_PERMANENT" if echecs and not transitoires
                      else "ECHEC_OUTIL" if echecs or rep.get("status") != "completed"
                      else "DONNEE_INSUFFISANTE")
            observe_texte = (f"statut={rep.get('status')} · {len(texte)} car. · "
                             f"outils={ {n: v['etat'] + (chr(47) + v['code'] if v['code'] not in ('-', '0') else '')
                                        for n, v in marqueurs['outils'].items()} or '-' }"
                             + (f" · refus={','.join(refus)}" if refus else ""))
            observations[capacite] = {"statut": statut, "echecs": echecs, "insuffisant": insuff,
                                     "permanents": permanents, "transitoires": transitoires,
                                     "refus": refus, "duree_s": rep.get("duree_s")}
            journal.entree("OBSERVE", agent=rep.get("agent_name") or capacite, outil=";".join(echecs) or
                           (";".join(insuff) if insuff else None),
                           action="observation_volet", resultat_attendu=attendus.get(capacite),
                           resultat_observe=observe_texte, statut=statut,
                           tentatives=1, erreur=rep.get("error"),
                           preuve=str(journal.dossier / "experts" / f"{capacite}.md"))
            trace.ajoute("OBSERVE", capacite, observe_texte, statut=statut, echecs=echecs)
        return observations

    @staticmethod
    def decider(observations: dict[str, dict], journal: JournalMission) -> dict[str, str]:
        """DECIDE : CONTINUE / ADAPT (une seule relance) / ESCALATE, par volet."""
        decisions: dict[str, str] = {}
        for capacite, o in observations.items():
            if o["statut"] == "OK":
                decisions[capacite] = "CONTINUE"
            elif o["statut"] == "ECHEC_OUTIL":
                decisions[capacite] = "ADAPT"       # une relance controlee est autorisee
            else:
                # ECHEC_PERMANENT ou donnee insuffisante : pas de relance inutile,
                # on continue en declarant la donnee manquante (LAB 13).
                decisions[capacite] = "CONTINUE"
            journal.entree("DECIDE", agent="AGROGUIDCI Agent Agronome Expert", action="decision_volet",
                           resultat_attendu="statut OK", resultat_observe=f"volet {capacite} = "
                           f"{o['statut']}", decision=decisions[capacite], statut=o["statut"],
                           tentatives=1, approbation_humaine=None)
        return decisions

    def adapter(self, demande: str, clarification: dict, a_relancer: list[Expertise],
                observations: dict[str, dict], trace: Trace, journal: JournalMission) -> dict[str, dict]:
        """ADAPT : UNE seule relance par volet, sans dupliquer une action sensible."""
        if not a_relancer:
            return {}
        consigne = ("RELANCE APRES ECHEC D'OUTIL. La tentative precedente a echoue ; ne reprends "
                    "pas une valeur inventee. Si l'outil reste indisponible, ecris-le et indique "
                    "precisement la donnee manquante et qui peut la fournir.")
        contexte = self.contexte_consigne(clarification) + "\n" + consigne
        repartis: dict[str, dict] = {}
        for expert in a_relancer:
            debut = time.time()
            dire("ADAPT", f"relance unique de « {expert.capacite} » (tentative 2)")
            journal.entree("ADAPT", agent=expert.nom, action="relance_controlee",
                           resultat_attendu="obtenir le volet malgre l'echec de l'outil",
                           resultat_observe=";".join(observations[expert.capacite]["echecs"]) or "-",
                           decision="RETRY", statut="EN_COURS", tentatives=2)
            try:
                rep = self.orch.deleguer(expert.capacite, f"{demande}\n\nCONTEXTE CLARIFIE PAR LE "
                                                          f"COORDONNATEUR\n{contexte}",
                                         action="expertise", timeout=self.timeout)
            except Exception as e:
                rep = {"status": "error", "error": str(e)}
            rep["duree_s"] = round(time.time() - debut, 2)
            repartis[expert.capacite] = rep
            trace.ajoute("ADAPT", expert.capacite, f"tentative 2 : {rep.get('status')} "
                                                   f"({rep.get('duree_s')}s)", statut=rep.get("status"))
        return repartis

    def verifier(self, resultats: dict[str, dict], synthese: str, dossier: Path, trace: Trace,
                 journal: JournalMission) -> dict:
        """VERIFY : controles independants (LAB 14) avant toute conclusion."""
        v = verif.verifier_mission(resultats, synthese, dossier)
        journal.entree("VERIFY", agent="AGROGUIDCI Agent Agronome Expert", action="verification_resultat",
                       resultat_attendu="unites et calculs coherents, sources presentes",
                       resultat_observe=f"statut={v['statut']} · {len(v['alertes'])} alerte(s)",
                       statut=v["statut"], tentatives=1, preuve=str(dossier / "verification.md"),
                       erreur="; ".join(v["alertes"])[:400] or None)
        trace.ajoute("VERIFY", "AGROGUIDCI", f"statut={v['statut']} · {len(v['alertes'])} alerte(s)",
                     alertes=v["alertes"][:10])
        (dossier / "verification.md").write_text(verif.tableau(v), encoding="utf-8")
        return v

    def ecrire_volets(self, resultats: dict[str, dict], dossier: Path, trace: Trace) -> None:
        """Ecrit les volets bruts et rapatrie les donnees produites par les outils."""
        (dossier / "experts").mkdir(exist_ok=True)
        (dossier / "outils").mkdir(exist_ok=True)
        for capacite, rep in resultats.items():
            texte = (rep.get("result") or f"(volet non traite : {rep.get('error') or rep.get('status')})")
            (dossier / "experts" / f"{capacite}.md").write_text(
                texte + f"\n\n<!-- statut={rep.get('status')} agent={rep.get('agent_name')} "
                        f"tache={rep.get('task_id')} duree={rep.get('duree_s')}s -->",
                encoding="utf-8")
            origine = re.search(r"<!-- outils_dir=(.+?) -->", texte)
            if origine:
                src = Path(origine.group(1).strip())
                if src.is_dir():
                    dest = dossier / "outils" / capacite
                    try:
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                        trace.ajoute("RECUPERATION", capacite,
                                     f"donnees outillees copiees dans {dest}")
                    except OSError as e:
                        trace.ajoute("RECUPERATION", capacite, f"copie impossible : {e}")

    # -- pipeline complet -------------------------------------------------
    def journaliser_supervision(self, entree: dict) -> Path:
        """Journal global de supervision : une ligne JSON par mission.

        Les identifiants directs (telephone, e-mail) sont masques : la supervision
        n'en a pas besoin, et un journal se conserve plus longtemps qu'une mission.
        """
        f = ROOT / "out" / "supervision.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(masquer_champs(entree), ensure_ascii=False) + "\n")
        return f

    def traiter(self, demande: str, domaines_forces: list[str] | None = None,
                etiquette: str | None = None) -> dict:
        if not self.orch.health():
            raise RuntimeError(f"orchestrateur injoignable sur {self.orch.base} : "
                               "demarre-le (python demarrer_agroguidci.py)")
        dossier = dossier_sortie(etiquette=etiquette)
        trace = Trace(demande=demande, dossier=dossier)
        reseau = etat_reseau(self.orch)
        trace.ajoute("DEMANDE", "producteur", demande[:160], dossier=str(dossier))
        trace.ajoute("RESEAU", "orchestrateur",
                     f"{len(reseau['agents'])} agent(s) pertinent(s) declares",
                     agents=[a["name"] for a in reseau["agents"]])
        self.presence()

        clarification = self.clarifier(demande, trace)
        (dossier / "clarification.json").write_text(
            json.dumps(clarification, ensure_ascii=False, indent=2), encoding="utf-8")
        # ------------------------------------------------------------ GOAL / PLAN
        journal = JournalMission(demande, dossier)
        ciblable, manques = mission_ciblable(demande)
        journal.entree("GOAL", action="clarification_besoin",
                       resultat_attendu="besoin reformule, hypotheses et manques identifies",
                       resultat_observe=(clarification.get("besoin_principal")
                                         + ("" if ciblable else " · mission non ciblable : manque "
                                            + " ; ".join(manques))),
                       statut="OK" if ciblable else "EN_ATTENTE_INFORMATION",
                       decision="CONTINUE" if ciblable else "STOP",
                       source="clarification.json", preuve=str(dossier / "clarification.json"))
        trace.ajoute("GOAL", "AGROGUIDCI", f"mission {journal.mission_id}")
        experts = self.selectionner(demande, clarification, trace, domaines_forces)
        attendus = {e.capacite: (e.resume[:130] if e.cle != PRINCIPAL.cle
                                 else "volet agronomique traite en propre par l'agent principal")
                    for e in experts}
        journal.entree("PLAN", action="planning_mission",
                       resultat_attendu="selection des competences utiles a la mission",
                       resultat_observe=f"{len(experts)} volet(s) : "
                                        + ", ".join(e.cle for e in experts),
                       statut="OK", source="experts.py", preuve=str(dossier / "trace.json"))
        # Permissions (PARTIE C) : une demande d'action interdite est refusee d'emblee.
        interdits = intentions_interdites(demande)
        for i in interdits:
            journal.entree("PLAN", action="permission",
                           resultat_attendu="action autorisee par la matrice",
                           resultat_observe=f"`{i['action']}` ({i['libelle']}) : mode {i['mode']}",
                           statut="ARRETEE_PERMISSION", decision="STOP", erreur=i["regle"],
                           source="permissions.py", preuve=str(dossier / "trace.json"))
            trace.ajoute("PERMISSION", i["action"], f"refus : {i['regle'][:100]}")
            dire("PERMISSION", f"action `{i['action']}` refusee ({i['mode']}) : {i['libelle']}")
        # Le volet agronomique est traite EN PROPRE par l'agent principal : il EST
        # l'agronome, le deleguer a un autre agent serait un detour inutile.
        resultats: dict[str, dict] = {}
        a_deleguer: list[Expertise] = []
        for e in experts:
            if e.cle == PRINCIPAL.cle:
                resultats[e.capacite] = self.volet_en_propre(demande, clarification, trace)
            else:
                a_deleguer.append(e)
        resultats.update(self.coordonner(demande, a_deleguer, clarification, trace))
        # ------------------------------------------------------------ ACT
        for capacite, rep in resultats.items():
            journal.entree("ACT", agent=rep.get("agent_name") or capacite, action="execution_volet",
                           resultat_attendu=attendus.get(capacite),
                           resultat_observe=f"statut={rep.get('status')} · "
                                            f"{len(rep.get('result') or '')} car. · "
                                            f"{rep.get('duree_s')}s",
                           statut="OK" if rep.get("status") == "completed" else "ECHEC",
                           tentatives=1, erreur=rep.get("error"),
                           source=str(rep.get("agent_id") or rep.get("agent_name")),
                           preuve=str(dossier / "experts" / f"{capacite}.md"))

        self.ecrire_volets(resultats, dossier, trace)

        # ------------------------------------------- OBSERVE / DECIDE / ADAPT
        observations = self.observer(resultats, trace, journal, attendus)
        decisions = self.decider(observations, journal)
        a_relancer = [EXPERTISES[c] for c, d in decisions.items()
                      if d == "ADAPT" and c in EXPERTISES]
        if a_relancer:
            repartis = self.adapter(demande, clarification, a_relancer, observations, trace, journal)
            for capacite, rep in repartis.items():
                if rep.get("status") == "completed" and len(rep.get("result") or "") > 200:
                    resultats[capacite] = rep
            self.ecrire_volets({c: resultats[c] for c in repartis if c in resultats}, dossier, trace)
            observations = self.observer(resultats, trace, journal, attendus)
            for expert in a_relancer:
                o = observations.get(expert.capacite, {})
                journal.entree("DECIDE", agent="AGROGUIDCI Agent Agronome Expert",
                               action="decision_apres_relance",
                               resultat_attendu="volet exploitable apres relance",
                               resultat_observe=f"{expert.capacite} = {o.get('statut')}",
                               decision="CONTINUE" if o.get("statut") != "ECHEC_OUTIL" else "ESCALATE",
                               statut=o.get("statut", "ECHEC_OUTIL"), tentatives=2,
                               approbation_humaine=("demandee" if o.get("statut") == "ECHEC_OUTIL"
                                                    else None))

        # ------------------------------------------------------------ VERIFY
        synthese = self.synthetiser(demande, clarification, resultats, trace)
        verification = self.verifier(resultats, synthese["texte"], dossier, trace, journal)
        etat = journal.etat_final()
        if verification["statut"] == "ECHEC" and etat == "TERMINEE_VERIFIEE":
            etat = "ECHEC_OUTIL"
        validations = en_attente_validation()
        decision_finale = ("ESCALATE" if etat in ("A_VALIDER", "ESCALADE_HUMAINE", "ARRETEE_PERMISSION")
                           else "STOP" if etat in ("ECHEC_OUTIL", "EN_ATTENTE_INFORMATION")
                           else "CONTINUE")
        journal.entree("DECIDE", agent=NOM, action="decision_finale",
                       resultat_attendu="mission verifiee, conclusion tracable",
                       resultat_observe=f"etat={etat} · verification={verification['statut']} · "
                                        f"{len(validations)} validation(s) en attente",
                       decision=decision_finale, statut=etat, tentatives=1,
                       approbation_humaine=("demandee" if validations else None),
                       preuve=str(dossier / "verification.md"))
        chemin = self.rapport(demande, clarification, resultats, synthese, dossier, trace,
                              journal=journal, verification=verification, etat_final=etat,
                              permissions_refusees=interdits)
        journal.ecrire_markdown(etat)
        trace.ajoute("ECRITURE", "AGROGUIDCI", f"rapport : {chemin} · etat final : {etat}")
        self.journaliser_supervision({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mission_id": journal.mission_id,
            "dossier": dossier.name,
            "demande": demande[:200].replace("\n", " "),
            "duree_s": trace.etapes[-1]["ecoule_s"],
            "agents": [par_capacite(c).nom if par_capacite(c) else c for c in resultats],
            "statuts": {c: r.get("status") for c, r in resultats.items()},
            "etat_final": etat,
            "verification": verification["statut"],
            "validations_en_attente": len(validations),
            "rapport": str(chemin),
        })
        trace.ajoute("SUPERVISION", "AGROGUIDCI",
                     f"journalise dans out/supervision.jsonl "
                     f"({len(validations)} action(s) sensible(s) en attente de validation)")
        trace.ecrire(meta={
            "version": VERSION,
            "mission_id": journal.mission_id,
            "etat_final": etat,
            "verification": {"statut": verification["statut"],
                             "alertes": verification["alertes"][:20]},
            "permissions_refusees": [i["action"] for i in interdits],
            "agent_principal": NOM,
            "sous_agents_disponibles": list(SOUS_AGENTS),
            "modele_llm": self.llm.modele,
            "llm": self.llm.statistiques,
            "reseau_initial": reseau,
            "capacites_consultees": list(resultats),
            "besoin_principal": clarification.get("besoin_principal"),
            "rapport": str(chemin),
        })
        return {"dossier": dossier, "rapport": chemin, "trace": dossier / "trace.json",
                "clarification": clarification, "resultats": resultats, "synthese": synthese,
                "mission": journal, "etat_final": etat, "verification": verification}


# --------------------------------------------------------------------------- mode agent
def servir(orch: Orchestrateur, llm: LLM, periode_ms: int = 10000) -> int:
    """L'agent principal repond aux taches deleguees : « agronomie » (en propre) et
    « coordination_agroguidci » (mission complete)."""
    coord = Coordonnateur(orch, llm)
    jeton = coord._jeton()
    caps = CAPACITES
    orch.register(AGENT_ID, NOM, caps, PRINCIPAL.identite["endpoint"], role=ROLE)
    orch.battement(jeton, caps)
    dire("EN LIGNE", f"{NOM} — capacites {', '.join(caps)} — "
                     f"modele {llm.modele or 'a resoudre'} — {orch.base}")
    verrou = threading.Lock()
    while True:
        if not verrou.locked():
            with verrou:
                orch.battement(jeton, caps)
                for tache in orch.taches(jeton):
                    demande = tache.get("instruction") or ""
                    capacite = (tache.get("capability") or "").strip()
                    dire("TACHE", f"{tache['task_id']} capacite={capacite}")
                    try:
                        if capacite == PRINCIPAL.capacite:
                            # volet agronomique : l'agent principal repond en propre
                            kb = BaseConnaissances(PRINCIPAL.fichiers).charger()
                            r = executer_agent(PRINCIPAL, demande, llm, kb, action=tache.get("action"))
                            orch.remonter(jeton, tache["task_id"], r.get("status", "completed"),
                                          resultat=r.get("result"), erreur=r.get("error"))
                            dire("RESULTAT", f"{tache['task_id']} {r.get('status')} "
                                             f"(volet agronomique en propre)")
                        else:
                            res = coord.traiter(demande, etiquette=f"tache-{tache['task_id'][-6:]}")
                            orch.remonter(jeton, tache["task_id"], "completed",
                                          resultat=f"{res['synthese']['texte']}\n\n---\n"
                                                   f"Rapport complet : {res['rapport']}")
                            dire("RESULTAT", f"{tache['task_id']} traite → {res['rapport'].name}")
                    except Exception as e:
                        orch.remonter(jeton, tache["task_id"], "failed",
                                      erreur=f"traitement en echec : {e}")
                        dire("ECHEC", f"{tache['task_id']} : {e}")
        time.sleep(max(periode_ms, 3000) / 1000.0)


def main() -> int:
    p = argparse.ArgumentParser(description=f"{SERVICE} — {NOM}")
    p.add_argument("--demande", help="demande du producteur (une seule)")
    p.add_argument("--domaines", help="capacites imposees, separees par des virgules")
    p.add_argument("--etiquette", help="suffixe du dossier de sortie")
    p.add_argument("--orchestrateur", default=None)
    p.add_argument("--timeout", type=float, default=420.0, help="attente max par delegation (s)")
    p.add_argument("--etat", action="store_true", help="etat du reseau d'agents et sortie")
    p.add_argument("commande", nargs="?", default="run", choices=["run", "work"])
    args = p.parse_args()

    orch = Orchestrateur(args.orchestrateur)
    llm = LLM()

    if args.etat:
        etat = etat_reseau(orch)
        print(json.dumps(etat, ensure_ascii=False, indent=2))
        return 0 if etat["joignable"] else 2

    if args.commande == "work":
        if not orch.health():
            dire("ERREUR", f"orchestrateur injoignable sur {orch.base}")
            return 2
        return servir(orch, llm)

    if not args.demande:
        p.error("--demande est requis (ou la commande 'work')")

    domaines = [d.strip() for d in (args.domaines or "").split(",") if d.strip()]
    coord = Coordonnateur(orch, llm, timeout_delegation=args.timeout)
    try:
        res = coord.traiter(args.demande, domaines_forces=domaines or None, etiquette=args.etiquette)
    except (RuntimeError, OSError) as e:
        dire("ERREUR", str(e))
        return 2
    print("\n" + "=" * 72)
    print(res["synthese"]["texte"])
    print("=" * 72)
    print(f"\netat final : {res['etat_final']} · verification : {res['verification']['statut']}")
    print(f"rapport : {res['rapport']}\nmission : {res['mission'].chemin}\n"
          f"trace   : {res['trace']}\ndossier : {res['dossier']}")
    for a in res["verification"]["alertes"][:8]:
        print(f"  ! {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

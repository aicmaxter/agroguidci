"""
serveur_api.py — API HTTP du moteur AGROGUIDCI (destinée à un VPS).

Expose le pipeline complet (clarification -> sélection -> coordination -> synthèse
-> vérification) derrière HTTP, pour que la vitrine (ou tout autre client) parle au
VRAI moteur : orchestreur local, sept agents, outils réels, journal de mission.

    python serveur_api.py                 # 0.0.0.0:8080 (uvicorn)
    AGRO_API_KEY=... python serveur_api.py

Endpoints
    GET  /health          état du service + orchestrateur + agents en ligne (public)
    GET  /api/demande     mode d'emploi du POST (public)
    POST /api/demande     { texte, profil? } -> rapport complet (protégé par clé)
    GET  /api/etat        réseau d'agents + dernières missions (protégé)

Sécurité
    - clé d'API obligatoire (X-API-Key ou Authorization: Bearer) ; le service refuse
      de démarrer sans clé, sauf AGRO_SANS_AUTH=1 (poste de dev uniquement) ;
    - comparaison à temps constant, taille de corps bornée, texte borné ;
    - CORS limité aux origines déclarées (AGRO_CORS_ORIGINS) ;
    - concurrence bornée (AGRO_MAX_CONCURRENCE) : une coordination sature vite ;
    - les erreurs renvoyées ne contiennent jamais clé, chemin absolu ni trace interne.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import sys
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastapi import Depends, FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from coordinateur import Coordonnateur, etat_reseau  # noqa: E402
from confidentialite import masquer_champs  # minimisation des journaux
import conversations as conv  # fils de discussion (SQLite, volume agro-data)
from agrokit import Orchestrateur  # noqa: E402
from experts import EXPERTISES  # noqa: E402

VERSION = "1.0"
CLE_API = (os.environ.get("AGRO_API_KEY") or "").strip()
SANS_AUTH = os.environ.get("AGRO_SANS_AUTH", "") in ("1", "true", "oui")
ORIGINES = [o.strip() for o in (os.environ.get("AGRO_CORS_ORIGINS")
                                or "https://agroguidci.vercel.app,http://127.0.0.1:8099,http://localhost:8099"
                                ).split(",") if o.strip()]
MAX_CONCURRENCE = max(1, int(os.environ.get("AGRO_MAX_CONCURRENCE", "2") or 2))
BUDGET_S = float(os.environ.get("AGRO_BUDGET_S", "300") or 300)
MAX_TEXTE = int(os.environ.get("AGRO_MAX_TEXTE", "4000") or 4000)

if not CLE_API and not SANS_AUTH:
    raise SystemExit("AGRO_API_KEY est requis (ou AGRO_SANS_AUTH=1 pour un poste de dev).")

_semaphore = asyncio.Semaphore(MAX_CONCURRENCE)

# --- missions asynchrones -----------------------------------------------------
# Une coordination dure 30 à 120 s : trop long pour un proxy serverless (limite de
# durée d'exécution) et fragile pour un navigateur. Le mode `async` rend un identifiant
# tout de suite et le client interroge /api/missions/{id}.
_VERROU = threading.Semaphore(MAX_CONCURRENCE)
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
DUREE_JOB_MAX = 3600          # purge des missions terminées après une heure


def _job_ecrire(jid: str, **champs: Any) -> None:
    with _JOBS_LOCK:
        _JOBS.setdefault(jid, {}).update(champs)
        _JOBS[jid]["maj"] = time.time()
        if len(_JOBS) > 200:                     # purge opportuniste
            vieux = [k for k, v in _JOBS.items()
                     if v.get("statut") in ("termine", "echec")
                     and time.time() - v.get("maj", time.time()) > DUREE_JOB_MAX]
            for k in vieux:
                _JOBS.pop(k, None)


def _job_lire(jid: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(jid)
        return dict(job) if job else None


def _executer_job(jid: str, texte: str, profil: Profil | None) -> None:
    """Exécute une mission en tâche de fond et publie son état."""
    if not _VERROU.acquire(timeout=BUDGET_S):
        _job_ecrire(jid, statut="echec", erreur="moteur occupé : réessayez dans un instant")
        return
    debut = time.perf_counter()
    try:
        coord = Coordonnateur()
        resultat = coord.traiter(texte, None, None)
        duree = time.perf_counter() - debut
        corps = _enveloppe(texte, profil, resultat, duree)
        _job_ecrire(jid, statut="termine", duree_s=round(duree, 1), data=corps)
        journalise(evenement="mission_async", id=corps["id"], jid=jid,
                   etat=corps["etat_final"], duree_s=round(duree, 1))
    except RuntimeError as e:
        _job_ecrire(jid, statut="echec",
                    erreur="moteur indisponible : orchestrateur ou agents non démarrés")
        journalise(evenement="job_moteur_indisponible", jid=jid, detail=str(e)[:200])
    except Exception as e:                       # jamais de trace interne côté client
        _job_ecrire(jid, statut="echec", erreur=f"erreur du moteur ({type(e).__name__})")
        journalise(evenement="job_erreur", jid=jid, type=type(e).__name__)
    finally:
        _VERROU.release()


# --------------------------------------------------------------------------- utils
def journalise(**champs: Any) -> None:
    """Journal JSON sur une ligne (lisible par systemd / docker logs).

    Les donnees personnelles (telephone, e-mail, longues references) sont masquees
    avant ecriture : un journal n'a pas a conserver un numero de producteur
    (loi n° 2013-450, minimisation).
    """
    champs.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    print(json.dumps(masquer_champs(champs), ensure_ascii=False), flush=True)


def _egales(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def garde_cle(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    """Vérifie la clé d'API (en-tête X-API-Key ou Bearer)."""
    if SANS_AUTH:
        return
    fournie = (x_api_key or "").strip()
    if not fournie and authorization and authorization.lower().startswith("bearer "):
        fournie = authorization[7:].strip()
    if not fournie or not _egales(fournie, CLE_API):
        journalise(evenement="auth_refusee", raison="cle absente ou invalide")
        raise HTTPException(status_code=401, detail="clé d'API absente ou invalide")


# --------------------------------------------------------------------------- app
app = FastAPI(
    title="AGROGUIDCI — moteur",
    version=VERSION,
    description="Moteur multi-agents de conseil agricole (Côte d'Ivoire). "
                "POST /api/demande pour une mission complète.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINES,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    max_age=600,
)


class Profil(BaseModel):
    localite: str | None = Field(default=None, max_length=120)
    filiere: str | None = Field(default=None, max_length=120)
    surface_ha: float | None = Field(default=None, ge=0, le=100000)
    budget_fcfa: float | None = Field(default=None, ge=0, le=10**12)
    experience: str | None = Field(default=None, max_length=60)
    objectif: str | None = Field(default=None, max_length=200)


class Demande(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    texte: str = Field(min_length=5, max_length=MAX_TEXTE)
    profil: Profil | None = None
    asynchrone: bool = Field(default=False, alias="async")


def _composer(texte: str, profil: Profil | None) -> str:
    """Ajoute les informations de profil à la demande, sans en inventer aucune."""
    if profil is None:
        return texte
    faits = []
    if profil.localite:
        faits.append(f"localité : {profil.localite}")
    if profil.filiere:
        faits.append(f"filière : {profil.filiere}")
    if profil.surface_ha is not None:
        faits.append(f"surface : {profil.surface_ha:g} ha")
    if profil.budget_fcfa is not None:
        faits.append(f"budget : {profil.budget_fcfa:,.0f} FCFA".replace(",", " "))
    if profil.experience:
        faits.append(f"expérience : {profil.experience}")
    if profil.objectif:
        faits.append(f"objectif : {profil.objectif}")
    if not faits:
        return texte
    return texte + "\n\nInformations fournies par le producteur — " + " · ".join(faits)


def _sources(resultats: dict[str, dict]) -> list[dict]:
    """Fichiers de connaissances réellement mobilisés, par volet traité."""
    experts = EXPERTISES.values() if isinstance(EXPERTISES, dict) else EXPERTISES
    par_capacite = {e.capacite: e for e in experts}
    vus, sorties = set(), []
    for capacite in (resultats or {}):
        exp = par_capacite.get(capacite)
        if not exp:
            continue
        for fichier in (exp.fichiers or ()):
            nom = Path(str(fichier)).name
            if nom in vus:
                continue
            vus.add(nom)
            sorties.append({"source": nom, "section": f"volet {capacite}"})
    return sorties


def _enveloppe(demande: str, profil: Profil | None, resultat: dict[str, Any],
               duree: float) -> dict[str, Any]:
    """Traduit le retour du moteur en JSON stable pour les clients HTTP."""
    clarification = resultat.get("clarification") or {}
    verification = resultat.get("verification") or {}
    journal = resultat.get("mission")
    entrees = list(getattr(journal, "entrees", []) or [])
    resultats = resultat.get("resultats") or {}
    etat = resultat.get("etat_final") or (journal.etat_final() if journal else "INCONNU")
    mission_id = getattr(journal, "mission_id", None) or time.strftime("mis_%Y%m%d-%H%M%S")

    questions = []
    for cle in ("questions", "informations_manquantes", "manques"):
        valeur = clarification.get(cle)
        if isinstance(valeur, list):
            questions = [str(v) for v in valeur if str(v).strip()]
            if questions:
                break

    if isinstance(resultat.get("synthese"), dict):
        synthese = resultat.get("synthese") or {}
        texte_reponse = str(synthese.get("texte") or "")
        avis = [str(a) for a in (synthese.get("avis") or [])]
        sections_manquantes = [str(s) for s in (synthese.get("sections_manquantes") or [])]
    else:
        texte_reponse = str(resultat.get("synthese") or "")
        avis, sections_manquantes = [], []
    alertes = [str(a) for a in (verification.get("alertes") or [])] + avis + sections_manquantes

    decisions = [e.get("decision") for e in entrees if e.get("decision")]
    return {
        "id": mission_id,
        "demande": demande,
        "profil": profil.model_dump(exclude_none=True) if profil else {},
        "domaines": list(resultats.keys()),
        "etat_final": etat,
        "decision": decisions[-1] if decisions else "CONTINUE",
        "duree_s": round(duree, 1),
        "rapport": {
            "besoin": clarification.get("besoin_principal") or "",
            "hypotheses": [str(h) for h in (clarification.get("hypotheses") or [])],
            "manques": questions,
            "reponse": texte_reponse,
            "chiffres": [],
            "sources": _sources(resultats),
            "prochaine_action": questions[0] if questions else None,
            "limites": [
                "aucune prescription de produit phytosanitaire ni de dosage",
                "aucun diagnostic vétérinaire : renvoi au vétérinaire de zone",
                "prix de marché non connectés : à relever localement",
            ],
        },
        "verification": {"statut": verification.get("statut"),
                         "alertes": verification.get("alertes") or []},
        "alertes": alertes,
        "etapes": [{"phase": e.get("phase"), "agent": e.get("agent"),
                    "action": e.get("action"), "statut": e.get("statut"),
                    "decision": e.get("decision"), "horodatage": e.get("horodatage")}
                   for e in entrees],
        "persistance": True,
        "cree_le": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# --------------------------------------------------------------------------- routes
@app.get("/health")
def sante() -> dict[str, Any]:
    """État public : le service répond, l'orchestrateur et les agents sont-ils là ?"""
    try:
        orch = Orchestrateur()
        joignable = orch.health()
        reseau = etat_reseau(orch) if joignable else {"agents": []}
        agents = [a.get("name") for a in reseau.get("agents", [])]
    except Exception as e:                              # jamais de trace interne
        joignable, agents = False, []
        journalise(evenement="health_erreur", type=type(e).__name__)
    return {"status": "ok" if joignable else "degrade", "version": VERSION,
            "orchestrateur": joignable, "agents_en_ligne": len(agents), "agents": agents}


@app.get("/api/demande")
def mode_emploi() -> dict[str, Any]:
    return {
        "usage": "POST /api/demande",
        "corps": {"texte": "votre question (5 caractères minimum)",
                  "profil": {"localite": "Bouaké", "filiere": "igname", "surface_ha": 2,
                             "budget_fcfa": 300000, "experience": "debutant",
                             "objectif": "vendre"}},
        "entete": "X-API-Key: <clé> (ou Authorization: Bearer <clé>)",
        "exemple": {"texte": "J'ai 2 hectares et 300 000 FCFA, je débute, que puis-je faire ?",
                    "profil": {"localite": "Korhogo", "filiere": "riz", "surface_ha": 2}},
        "reponse": "id, etat_final, domaines, rapport{besoin, reponse, hypotheses, manques, "
                   "sources, limites}, alertes, etapes",
    }


@app.post("/api/demande")
async def demande(d: Demande, _: None = Depends(garde_cle)) -> JSONResponse:
    """Lance une mission complète. Une coordination prend 10 à 120 secondes.

    `{"async": true}` rend immédiatement un identifiant à suivre sur /api/missions/{id}
    (indispensable derrière un proxy qui a une limite de durée d'exécution).
    """
    texte = _composer(d.texte.strip(), d.profil)
    if d.asynchrone:
        jid = "j_" + uuid.uuid4().hex[:12]
        _job_ecrire(jid, statut="en_cours", demande=d.texte.strip()[:200], debut=time.time())
        threading.Thread(target=_executer_job, args=(jid, texte, d.profil), daemon=True).start()
        journalise(evenement="job_cree", jid=jid)
        return JSONResponse(status_code=202,
                            content={"id": jid, "statut": "en_cours",
                                     "suivi": f"/api/missions/{jid}",
                                     "note": "interroger le champ 'suivi' toutes les 3 s"})
    if _semaphore.locked():
        journalise(evenement="sature", texte=d.texte[:60])
        return JSONResponse(status_code=429,
                            content={"erreur": "moteur occupé : réessayez dans un instant"})
    debut = time.perf_counter()
    async with _semaphore:
        try:
            coord = Coordonnateur()
            resultat = await asyncio.wait_for(
                asyncio.to_thread(coord.traiter, texte, None, None), timeout=BUDGET_S)
        except asyncio.TimeoutError:
            journalise(evenement="budget_depasse", texte=d.texte[:60], budget_s=BUDGET_S)
            return JSONResponse(status_code=504,
                                content={"erreur": f"mission interrompue après {BUDGET_S:.0f} s : "
                                                   "le moteur n'a pas conclu, aucune réponse inventée"})
        except RuntimeError as e:                     # orchestrateur injoignable, etc.
            journalise(evenement="moteur_indisponible", detail=str(e)[:200])
            return JSONResponse(status_code=503,
                                content={"erreur": "moteur indisponible : orchestrateur ou agents "
                                                   "non démarrés"})
        except Exception as e:                        # erreur interne : on déclare, on n'invente pas
            journalise(evenement="erreur_moteur", type=type(e).__name__)
            return JSONResponse(status_code=500,
                                content={"erreur": f"erreur du moteur ({type(e).__name__}) — "
                                                   "aucune réponse produite"})
    duree = time.perf_counter() - debut
    journalise(evenement="mission", id=getattr(resultat.get("mission"), "mission_id", None),
               etat=resultat.get("etat_final"), duree_s=round(duree, 1),
               domaines=list((resultat.get("resultats") or {}).keys()))
    try:
        corps = _enveloppe(d.texte.strip(), d.profil, resultat, duree)
    except Exception as e:                  # la mission a bien tourné : ne pas la perdre
        journalise(evenement="enveloppe_erreur", type=type(e).__name__)
        journal = resultat.get("mission")
        corps = {
            "id": getattr(journal, "mission_id", None) or time.strftime("mis_%Y%m%d-%H%M%S"),
            "demande": d.texte.strip(),
            "profil": d.profil.model_dump(exclude_none=True) if d.profil else {},
            "domaines": list((resultat.get("resultats") or {}).keys()),
            "etat_final": resultat.get("etat_final") or "INCONNU",
            "decision": "CONTINUE",
            "duree_s": round(duree, 1),
            "rapport": {"besoin": (resultat.get("clarification") or {}).get("besoin_principal") or "",
                        "hypotheses": [], "manques": [], "chiffres": [], "sources": [],
                        "reponse": resultat.get("synthese") or "",
                        "prochaine_action": None, "limites": []},
            "alertes": ["réponse partielle : le détail du rapport n'a pas pu être assemblé"],
            "etapes": [],
            "persistance": True,
            "cree_le": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    return JSONResponse(content={"data": corps})


@app.get("/api/missions/{jid}")
def mission(jid: str, _: None = Depends(garde_cle)) -> dict[str, Any]:
    """État d'une mission asynchrone : en_cours, termine (avec `data`) ou echec."""
    if not jid.startswith("j_") or len(jid) > 40:
        raise HTTPException(status_code=400, detail="identifiant de mission invalide")
    job = _job_lire(jid)
    if job is None:
        raise HTTPException(status_code=404,
                            detail="mission inconnue ou expirée (les états sont gardés 1 h)")
    job.pop("maj", None)
    if job.get("statut") == "en_cours":
        debut = job.get("debut") or time.time()
        job["ecoule_s"] = round(time.time() - debut, 1)
    return job


@app.get("/api/etat")
def etat(_: None = Depends(garde_cle)) -> dict[str, Any]:
    """Réseau d'agents vu par l'orchestrateur (protégé : noms et capacités internes)."""
    try:
        orch = Orchestrateur()
        if not orch.health():
            return {"orchestrateur": False, "agents": []}
        reseau = etat_reseau(orch)
        return {"orchestrateur": True,
                "agents": [{"name": a.get("name"), "status": a.get("status"),
                            "capabilities": a.get("capabilities")}
                           for a in reseau.get("agents", [])]}
    except Exception as e:
        journalise(evenement="etat_erreur", type=type(e).__name__)
        return {"orchestrateur": False, "agents": []}



# ------------------------------------------------- fiches cultures (contexte)
_FICHES: dict[str, dict] = {}
_FICHES_MTIME = 0.0


def fiches_cultures() -> dict[str, dict]:
    """Fiches publiées (content/cultures-*.json) : lues une fois, relues si modifiées."""
    global _FICHES, _FICHES_MTIME
    fichiers = sorted((ROOT / "content").glob("cultures-*.json"))
    mtime = max((f.stat().st_mtime for f in fichiers), default=0.0)
    if _FICHES and mtime <= _FICHES_MTIME:
        return _FICHES
    cultures: dict[str, dict] = {}
    for f in fichiers:
        try:
            cultures.update((json.loads(f.read_text(encoding="utf-8")) or {}).get("cultures") or {})
        except (OSError, ValueError):
            continue
    _FICHES, _FICHES_MTIME = cultures, mtime
    return _FICHES


def extrait_fiche(culture_id: str | None, limite: int = 1800) -> str:
    """Extrait compact de la fiche publiée pour une culture, joint à la demande.

    Le chat ouvert depuis une fiche doit repondre avec les chiffres et les limites
    DE CETTE FICHE (source interne verifiee), pas avec une agronomie generique.
    """
    cid = (culture_id or "").strip().lower()
    if not cid:
        return ""
    fiches = fiches_cultures()
    fiche = fiches.get(cid) or next(
        (v for v in fiches.values() if (v.get("nom") or "").strip().lower() == cid), None)
    if not fiche:
        return ""
    champs = [("Cycle", "cycle"), ("Fiabilité de la fiche", "confiance"),
              ("Variétés", "varietes"), ("Conditions", "conditions"),
              ("Calendrier", "calendrier"), ("Préparation du sol", "preparation"),
              ("Plantation / semis", "semis"), ("Entretien et fertilisation", "entretien"),
              ("Santé des plants", "sante"), ("Récolte", "recolte"),
              ("Conservation", "conservation"), ("Économie et prix", "economie"),
              ("Limites déclarées", "limites")]
    lignes = [f"- {titre} : {(fiche.get(cle) or '').strip()[:230]}"
              for titre, cle in champs if (fiche.get(cle) or "").strip()]
    if not lignes:
        return ""
    entete = (f"EXTRAIT DE LA FICHE CULTURE PUBLIÉE PAR AGROGUIDCI — « {fiche.get('nom')} » "
              f"(source interne, page /cultures/{cid}). À utiliser en priorité : reprends ses "
              "chiffres et ses limites, dis clairement ce qu'elle ne documente pas, et ne la "
              "contredis jamais sans l'expliquer.\n")
    return (entete + "\n".join(lignes))[:limite]


CONSIGNE_CHAT = (
    "[CONSIGNE_INTERNE] COMMENT RÉPONDRE (demande posée dans la chatbox du site)\n"
    "- Français simple et direct, phrases courtes, comme on explique à un producteur "
    "dans son champ : pas de jargon administratif.\n"
    "- Si un terme technique est indispensable (nématode, buttage, densité), explique-le "
    "en quelques mots entre parenthèses.\n"
    "- Donne d'abord la réponse concrète, ensuite les détails ; termine par ce qu'il faut "
    "vérifier sur place ou auprès d'un service technique.\n"
    "- Vouvoie le producteur, sans familiarité."
)


def _sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "")
                   if unicodedata.category(c) != "Mn").lower()


def culture_detectee(texte: str) -> str | None:
    """Culture citée dans la question, quand la page ne la fournit pas (accueil).

    On s'appuie sur les noms et surnoms des fiches (mots entiers, sans accents) :
    « combien d'igname par butte ? » -> igname. Aucune supposition au-delà des noms
    réellement publiés.
    """
    t = _sans_accents(texte or "")
    if not t:
        return None
    meilleur: tuple[int, str] | None = None
    for cid, fiche in fiches_cultures().items():
        candidats = [cid, fiche.get("nom") or ""]
        candidats += [p.strip() for p in (fiche.get("surnom") or "").split(",")]
        for mot in candidats:
            motif = _sans_accents(mot).strip()
            if len(motif) < 4:
                continue
            if re.search(rf"\b{re.escape(motif)}\b", t):
                if meilleur is None or len(motif) > meilleur[0]:
                    meilleur = (len(motif), cid)
    return meilleur[1] if meilleur else None


# ------------------------------------------------------- conversations (chat)
class NouvelleConversation(BaseModel):
    culture_id: str | None = Field(default=None, max_length=60)
    localite: str | None = Field(default=None, max_length=120)


class NouveauMessage(BaseModel):
    texte: str = Field(min_length=2, max_length=conv.MAX_MESSAGE)
    culture_id: str | None = Field(default=None, max_length=60)
    localite: str | None = Field(default=None, max_length=120)
    stade: str | None = Field(default=None, max_length=60)
    idempotency_key: str | None = Field(default=None, max_length=100)


def _session(x_session_token: str | None) -> str:
    """Session anonyme exigée par les routes de conversation (401 sinon)."""
    sid = conv.session_valide(x_session_token)
    if not sid:
        raise HTTPException(status_code=401, detail="session absente ou expirée")
    return sid


def _statut_message(etat: str | None) -> str:
    return {"TERMINEE_VERIFIEE": "termine",
            "A_VALIDER": "escalade",
            "ESCALADE_HUMAINE": "escalade",
            "ARRETEE_PERMISSION": "escalade",
            "EN_ATTENTE_INFORMATION": "clarification",
            "ECHEC_OUTIL": "echec"}.get(etat or "", "echec")


# Une consultation n'est débitée que si l'agent a réellement répondu : une
# clarification (il manque une information) ou un échec restent gratuits.
STATUTS_DEBITES = {"termine", "escalade"}


def _tronquer_reponse(texte: str) -> str:
    """Borne la réponse publiée dans le fil (conv.MAX_REPONSE), coupée sur un mot."""
    texte = (texte or "").strip()
    if len(texte) <= conv.MAX_REPONSE:
        return texte
    suffixe = "\n\n… (réponse abrégée)"
    coupe = texte[: conv.MAX_REPONSE - len(suffixe) - 2].rsplit(" ", 1)[0]
    return (coupe or texte[: conv.MAX_REPONSE - len(suffixe) - 2]) + suffixe


def _publier_avancement(cid: str, contenu: str, state: dict) -> None:
    """Publie un extrait réel dans le fil pendant la rédaction (jamais bloquant).

    Le premier extrait crée la bulle de l'agent (statut en_cours) ; les suivants la
    mettent à jour, au plus une fois toutes les ~1,2 s (la synthèse arrive par
    fragments : inutile d'écrire en base à chaque jeton). La réponse finale réutilise
    ce même message.
    """
    contenu = (contenu or "").strip()
    if not contenu:
        return
    # L'extrait des volets ne doit jamais être remplacé par un fragment de synthèse
    # plus court : le fil ne rétrécit pas sous les yeux du producteur.
    if state.get("id") is not None and len(contenu) < int(state.get("taille") or 0):
        return
    maintenant = time.monotonic()
    if state.get("id") is not None and maintenant - float(state.get("maj") or 0.0) < 1.2:
        return
    contenu = contenu[: conv.MAX_REPONSE]
    try:
        if state.get("id") is None:
            m = conv.ajouter_message(cid, "assistant", contenu, statut="en_cours")
            state["id"] = m["message_id"]
        else:
            conv.maj_message(state["id"], contenu=contenu, statut="en_cours")
        state["maj"] = maintenant
        state["taille"] = len(contenu)
    except Exception as e:                     # confort d'affichage : jamais une erreur
        journalise(evenement="chat_avancement_ignore", type=type(e).__name__)


def _executer_message(cid: str, mid: str, texte: str, profil: Profil | None,
                      sid: str | None = None) -> None:
    """Exécute une demande de chat et publie la réponse dans le fil."""
    if not _VERROU.acquire(timeout=BUDGET_S):
        conv.repondre(cid, mid, "Le moteur est occupé : réessayez dans un instant.", "echec",
                      erreur="moteur occupé")
        return
    avancement: dict[str, str | None] = {"id": None}
    try:
        coord = Coordonnateur()
        resultat = coord.traiter(texte, None, None,
                                 progres=lambda etape, txt: _publier_avancement(cid, txt, avancement))
        corps = _enveloppe(texte, profil, resultat, 0.0)
        etat = corps.get("etat_final")
        reponse = _tronquer_reponse((corps.get("rapport") or {}).get("reponse") or "")
        statut = _statut_message(etat)
        conv.repondre(cid, mid, reponse, statut,
                      mission_id=corps.get("id"),
                      sources=(corps.get("rapport") or {}).get("sources") or [],
                      assistant_id=avancement.get("id"))
        # Débit APRÈS la réponse, une seule fois par message (idempotent), et
        # seulement si l'agent a réellement répondu.
        if sid and statut in STATUTS_DEBITES and reponse.strip():
            reste = conv.consommer(sid, mid)
            journalise(evenement="credits_debite", message=mid,
                       reste=(reste or {}).get("total"), statut=statut)
        journalise(evenement="chat_reponse", id=corps.get("id"), etat=etat,
                   caracteres=len(reponse), avancement=bool(avancement.get("id")))
    except RuntimeError:
        journalise(evenement="chat_moteur_indisponible")
        _publier_echec(cid, mid, "Le moteur de l'agent agronome est indisponible : orchestrateur "
                       "ou agents non démarrés. Réessayez plus tard.", "moteur indisponible",
                       avancement.get("id"))
    except Exception as e:
        journalise(evenement="chat_erreur", type=type(e).__name__, detail=str(e)[:200])
        _publier_echec(cid, mid, "Une erreur technique est survenue : aucune réponse n'a été "
                       "produite.", f"erreur du moteur ({type(e).__name__})",
                       avancement.get("id"))
    finally:
        _VERROU.release()


def _publier_echec(cid: str, mid: str, texte: str, erreur: str,
                   assistant_id: str | None = None) -> None:
    """Publie un échec sans jamais laisser la question en « en_cours »."""
    try:
        conv.repondre(cid, mid, texte, "echec", erreur=erreur, assistant_id=assistant_id)
    except Exception as e:                     # dernier recours : clore la question
        journalise(evenement="chat_echec_publication", type=type(e).__name__)
        try:
            conv.maj_message(mid, statut="echec", erreur=erreur[:200])
        except Exception:
            pass


@app.post("/api/sessions")
def nouvelle_session(_: None = Depends(garde_cle)) -> dict[str, Any]:
    """Crée une session anonyme ; le jeton n'est rendu qu'une seule fois."""
    s = conv.creer_session()
    journalise(evenement="session_creee", session=s["session_id"])
    return {"session_id": s["session_id"], "session_token": s["session_token"],
            "expires_at": s["expires_at"]}


@app.get("/api/credits")
def etat_credits(x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
                 _: None = Depends(garde_cle)) -> dict[str, Any]:
    """Solde réel du compte anonyme (calculé en base, jamais depuis le navigateur).

    Le lot gratuit de la période courante est attribué ici de façon idempotente :
    recharger la page ou rejouer la requête ne crédite pas deux fois.
    """
    sid = _session(x_session_token)
    s = conv.solde(sid)
    s["packs"] = [
        {"id": "decouverte", "nom": "Pack Découverte", "prix_fcfa": 599, "credits": 30, "disponible": False},
        {"id": "avance", "nom": "Pack Avancé", "prix_fcfa": 3999, "credits": 200, "disponible": False},
    ]
    return s


@app.post("/api/conversations")
def nouvelle_conversation(corps: NouvelleConversation | None = None,
                          x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
                          _: None = Depends(garde_cle)) -> JSONResponse:
    sid = _session(x_session_token)
    corps = corps or NouvelleConversation()
    c = conv.creer_conversation(sid, corps.culture_id, corps.localite)
    journalise(evenement="conversation_creee", conversation=c["conversation_id"])
    return JSONResponse(status_code=201, content=c)


@app.get("/api/conversations/{cid}")
def lire_conversation(cid: str,
                      x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
                      _: None = Depends(garde_cle)) -> dict[str, Any]:
    sid = _session(x_session_token)
    f = conv.fil(sid, cid)
    if not f:
        # 404 et non 403 : ne jamais révéler l'existence d'un fil d'autrui
        raise HTTPException(status_code=404, detail="conversation inconnue")
    return f


@app.post("/api/conversations/{cid}/messages")
def envoyer_message(cid: str, d: NouveauMessage,
                    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
                    _: None = Depends(garde_cle)) -> JSONResponse:
    sid = _session(x_session_token)
    if not conv.conversation_de(sid, cid):
        raise HTTPException(status_code=404, detail="conversation inconnue")
    # Solde vérifié côté serveur AVANT toute exécution : aucun appel au moteur,
    # aucun message créé si le compte n'a plus de crédit.
    etat_credits = conv.solde(sid)
    if etat_credits["total"] < etat_credits["cout_consultation"]:
        return JSONResponse(status_code=402, content={
            "erreur": "Crédits épuisés : les 15 crédits gratuits reviennent à la prochaine période.",
            "credits": etat_credits,
        })
    contexte = []
    culture = (d.culture_id or "").strip() or culture_detectee(d.texte) or ""
    if culture:
        contexte.append(f"culture : {culture}")
    if d.localite:
        contexte.append(f"localité : {d.localite}")
    if d.stade:
        contexte.append(f"stade : {d.stade}")
    texte = d.texte.strip()
    saut = chr(10) * 2
    if contexte:
        texte = texte + saut + "Contexte fourni par la page — " + " · ".join(contexte)
        fiche = extrait_fiche(culture)
        if fiche:
            texte = texte + saut + saut + fiche
    texte = texte + saut + saut + CONSIGNE_CHAT
    try:
        msg = conv.ajouter_message(cid, "user", d.texte.strip(), statut="en_cours",
                                   idempotency_key=d.idempotency_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if msg.get("rejoue"):
        return JSONResponse(status_code=200, content={"message_id": msg["message_id"],
                                                      "statut": msg["statut"], "rejoue": True})
    thread = threading.Thread(target=_executer_message,
                              args=(cid, msg["message_id"], texte, None, sid), daemon=True)
    thread.start()
    journalise(evenement="chat_demande", conversation=cid, message=msg["message_id"])
    return JSONResponse(status_code=202, content={"message_id": msg["message_id"],
                                                  "statut": "en_cours", "rejoue": False})


@app.exception_handler(413)
async def _trop_gros(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=413, content={"erreur": "requête trop volumineuse"})


def main() -> int:
    import uvicorn

    hote = os.environ.get("AGRO_API_HOST", "0.0.0.0")
    port = int(os.environ.get("AGRO_API_PORT", "8080"))
    journalise(evenement="demarrage", version=VERSION, hote=hote, port=port,
               auth="cle" if not SANS_AUTH else "SANS AUTH (dev)",
               origines=ORIGINES, concurrence=MAX_CONCURRENCE, budget_s=BUDGET_S)
    uvicorn.run(app, host=hote, port=port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

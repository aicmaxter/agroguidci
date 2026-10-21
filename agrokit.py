"""
agrokit.py — briques partagees d'AGROGUIDCI.

Tout ce qui serait sinon duplique dans chaque agent du systeme :
  - le client de l'orchestrateur local (reseau local d'agents : POST /register,
    POST /delegate ; protocole multi-agent : enroll, heartbeat, taches, resultat) ;
  - le client LLM (DeepSeek) reellement utilise pour le raisonnement ;
  - le chargement de la base de connaissances, empreinte SHA-256 pour la tracabilite ;
  - le journal de trace : chaque decision, chaque appel, chaque resultat est
    horodate et exportable (JSON + markdown).

Regle de prudence : aucune reponse n'est inventee. Si le LLM ou la base de
connaissances ne permettent pas de repondre, l'agent le dit et explique pourquoi.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- env
def charge_env(chemin: Path | None = None) -> None:
    """Charge un .env (cle=valeur) sans ecraser l'environnement existant."""
    fichiers = [chemin] if chemin else [ROOT / ".env", Path.home() / "AppData/Local/hermes/.env"]
    for f in fichiers:
        if not f or not Path(f).exists():
            continue
        try:
            lignes = Path(f).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ligne in lignes:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, val = ligne.split("=", 1)
            cle = cle.strip()
            val = val.strip().strip('"').strip("'")
            if cle and val and cle not in os.environ:
                os.environ[cle] = val


charge_env()

ORCH = os.environ.get("AGRO_ORCH", os.environ.get("LAB_ORCH", "http://127.0.0.1:8000")).rstrip("/")
SERVICE = "AGROGUIDCI"


def cles_orchestrateur() -> dict[str, str]:
    """Cle operateur + cle d'enregistrement de l'orchestrateur local.

    Repli volontaire : l'orchestrateur et les agents tournent sur la meme machine
    et la cle est dans ~/orchestrator/.keys.json — evite un doublon de secret.
    """
    chemin = Path(os.environ.get("AGRO_KEYS", Path.home() / "orchestrator" / ".keys.json"))
    out: dict[str, str] = {}
    if chemin.exists():
        try:
            out = json.loads(chemin.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            out = {}
    if os.environ.get("LAB_MASTER_KEY"):
        out["admin_key"] = os.environ["LAB_MASTER_KEY"]
    if os.environ.get("ENROLLMENT_KEY"):
        out["enrollment_key"] = os.environ["ENROLLMENT_KEY"]
    return out


KEYS = cles_orchestrateur()
ADMIN_KEY = KEYS.get("admin_key", "")
ENROLLMENT_KEY = KEYS.get("enrollment_key", "")

# --------------------------------------------------------------------------- utils
def horodate() -> str:
    return time.strftime("%H:%M:%S")


def hms(secondes: float) -> str:
    return f"{secondes:.1f}s"


def sha256(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def dossier_sortie(base: str = "out", etiquette: str | None = None) -> Path:
    nom = f"{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{etiquette}" if etiquette else "")
    d = ROOT / base / nom
    d.mkdir(parents=True, exist_ok=True)
    return d


def dire(etape: str, message: str) -> None:
    """Trace lisible sur la sortie standard (docker logs / console).

    Les données personnelles (téléphone, e-mail, longues références) sont masquées
    ici, au point de sortie unique : c'est le seul moyen de garantir qu'aucun
    journal, y compris les traces de coordination, n'expose un numéro de producteur.
    """
    from confidentialite import masquer
    print(f"[{horodate()}] {etape:<14}{masquer(message)}", flush=True)


# --------------------------------------------------------------------------- HTTP
class ErreurOrchestrateur(RuntimeError):
    pass


def _http(method: str, url: str, corps: dict | None = None, entetes: dict | None = None,
          timeout: float = 60.0, tentatives: int = 3) -> tuple[int, Any]:
    """Requete JSON avec reprise sur erreurs transitoires (reseau capricieux ici)."""
    donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8") if corps is not None else None
    derniere: Exception | None = None
    for essai in range(tentatives):
        entetes_finaux = {"Accept": "application/json", "Connection": "close",
                          "User-Agent": os.environ.get("AGRO_USER_AGENT",
                                                       "AGROGUIDCI/1.1 (agent local; contact "
                                                       "aicmaxter@gmail.com)"),
                          "Content-Type": "application/json", **(entetes or {})}
        req = urllib.request.Request(url, data=donnees, method=method, headers=entetes_finaux)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                brut = r.read().decode("utf-8", errors="replace")
                try:
                    return r.status, (json.loads(brut) if brut else None)
                except ValueError:
                    return r.status, brut
        except urllib.error.HTTPError as e:
            brut = e.read().decode("utf-8", errors="replace")
            try:
                return e.code, json.loads(brut)
            except ValueError:
                return e.code, brut
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            derniere = e
            if essai < tentatives - 1:
                time.sleep(1.0 * (essai + 1))
    raise ErreurOrchestrateur(f"{method} {url} injoignable : {derniere}")


# --------------------------------------------------------------------------- orchestrateur
class Orchestrateur:
    """Client des deux protocoles de l'orchestrateur local."""

    def __init__(self, base: str | None = None) -> None:
        self.base = (base or ORCH).rstrip("/")

    # --- reseau local d'agents (X-API-Key operateur) -----------------------
    def health(self) -> bool:
        try:
            code, _ = _http("GET", f"{self.base}/health", timeout=8)
            return code == 200
        except ErreurOrchestrateur:
            return False

    def register(self, agent_id: str, name: str, capabilities: list[str], endpoint: str | None,
                 role: str = "expert") -> dict:
        code, data = _http("POST", f"{self.base}/register", {
            "agent_id": agent_id, "name": name, "endpoint": endpoint,
            "capabilities": capabilities, "role": role,
            "api_key": os.environ.get("LAB_AGENT_KEY", "AGRO-AGENT-KEY"),
        }, entetes={"X-API-Key": ADMIN_KEY}, timeout=20)
        if code != 200:
            raise ErreurOrchestrateur(f"/register {code} : {data}")
        return data

    def agents(self) -> list[dict]:
        code, data = _http("GET", f"{self.base}/agents", entetes={"X-API-Key": ADMIN_KEY}, timeout=20)
        if code != 200:
            raise ErreurOrchestrateur(f"/agents {code} : {data}")
        return data.get("agents", [])

    def deleguer(self, capacite: str, tache: str, action: str | None = None,
                 timeout: float = 420.0) -> dict:
        """Demande une competence au reseau — jamais a un agent en direct."""
        code, data = _http("POST", f"{self.base}/delegate",
                           {"capability": capacite, "task": tache, "action": action},
                           entetes={"X-API-Key": ADMIN_KEY}, timeout=timeout, tentatives=1)
        if code != 200:
            return {"status": "error", "capability": capacite, "error": f"HTTP {code} : {data}"}
        return data

    # --- protocole multi-agent (jeton d'agent) -----------------------------
    def enroler(self, identite: dict) -> str:
        if not ENROLLMENT_KEY:
            raise ErreurOrchestrateur("cle d'enregistrement absente (orchestrator/.keys.json).")
        code, data = _http("POST", f"{self.base}/api/v1/agents/enroll", identite,
                           entetes={"Authorization": f"Bearer {ENROLLMENT_KEY}"}, timeout=25)
        if code not in (200, 201):
            raise ErreurOrchestrateur(f"/enroll {code} : {data}")
        d = (data or {}).get("data") or data or {}
        jeton = d.get("agent_token") or d.get("token")
        if not jeton:
            raise ErreurOrchestrateur(f"/enroll : jeton absent de la reponse : {data}")
        return jeton

    def battement(self, jeton: str, capacites: list[str]) -> bool:
        try:
            code, _ = _http("POST", f"{self.base}/api/v1/agents/heartbeat",
                            {"status": "online", "capabilities": capacites},
                            entetes={"Authorization": f"Bearer {jeton}"}, timeout=15)
            return code in (200, 204)
        except ErreurOrchestrateur:
            return False

    def taches(self, jeton: str) -> list[dict]:
        code, data = _http("GET", f"{self.base}/api/v1/agents/tasks",
                           entetes={"Authorization": f"Bearer {jeton}"}, timeout=25)
        if code != 200:
            return []
        if isinstance(data, list):
            return data
        return (data or {}).get("data", {}).get("tasks", []) or (data or {}).get("tasks", [])

    def remonter(self, jeton: str, task_id: str, statut: str, resultat: str | None = None,
                 erreur: str | None = None) -> bool:
        code, _ = _http("POST", f"{self.base}/api/v1/agents/tasks/{task_id}/result",
                        {"status": statut, "result": resultat, "error": erreur},
                        entetes={"Authorization": f"Bearer {jeton}"}, timeout=30)
        return code == 200

    def tache(self, task_id: str) -> dict | None:
        code, data = _http("GET", f"{self.base}/api/v1/tasks",
                           entetes={"X-API-Key": ADMIN_KEY}, timeout=20)
        if code != 200:
            return None
        for t in (data or {}).get("data", {}).get("tasks", []):
            if t.get("task_id") == task_id:
                return t
        return None


# --------------------------------------------------------------------------- LLM
class ErreurLLM(RuntimeError):
    pass


class LLM:
    """Client DeepSeek minimal (aucune dependance externe).

    Le modele est resolu une fois aupres de /models quand c'est possible : le nom
    configure dans Hermes (deepseek-v4-flash) n'est pas forcement un nom d'API.
    """

    def __init__(self, modele: str | None = None, base: str | None = None,
                 cle: str | None = None, temperature: float = 0.2, max_tokens: int | None = None) -> None:
        self.base = (base or os.environ.get("AGRO_LLM_BASE", "https://api.deepseek.com/v1")).rstrip("/")
        self.cle = cle or os.environ.get("DEEPSEEK_API_KEY", "")
        self.modele = modele or os.environ.get("AGRO_LLM_MODEL", "")
        self.temperature = temperature
        # Les modeles de raisonnement decomptent leurs jetons de raisonnement
        # (reasoning_tokens) dans max_tokens : une limite serree tronque la reponse
        # visible sans avertissement. On vise donc large par defaut.
        self.max_tokens = max_tokens or int(os.environ.get("AGRO_LLM_MAX_TOKENS", "9000"))
        self._appels = 0
        self._jetons = 0
        self._verrou = threading.Lock()
        self.derniere_finish: str | None = None     # « stop », « length » (tronque)…
        self.dernier_usage: dict = {}

    # -- outils ------------------------------------------------------------
    @property
    def disponible(self) -> bool:
        return bool(self.cle)

    def modeles(self) -> list[str]:
        code, data = _http("GET", f"{self.base}/models",
                           entetes={"Authorization": f"Bearer {self.cle}"}, timeout=30)
        if code != 200 or not isinstance(data, dict):
            return []
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    def resoudre_modele(self) -> str:
        if self.modele:
            return self.modele
        if not self.cle:
            raise ErreurLLM("DEEPSEEK_API_KEY absente : aucun raisonnement LLM possible.")
        noms = self.modeles()
        prefere = os.environ.get("AGRO_LLM_MODEL_PREFERE", "deepseek-flash")
        for candidat in [prefere, "deepseek-chat", "deepseek-reasoner"]:
            if candidat and candidat in noms:
                self.modele = candidat
                return self.modele
        # a defaut : premier modele non specialise
        for n in noms:
            if "deepseek" in n and "coder" not in n:
                self.modele = n
                return self.modele
        self.modele = noms[0] if noms else "deepseek-chat"
        return self.modele

    def chat(self, messages: list[dict], temperature: float | None = None,
             max_tokens: int | None = None, json_mode: bool = False,
             tentatives: int = 3) -> str:
        if not self.cle:
            raise ErreurLLM("DEEPSEEK_API_KEY absente : impossible d'appeler le modele "
                            "(aucune reponse ne sera inventee a la place).")
        modele = self.resoudre_modele()
        corps: dict[str, Any] = {
            "model": modele,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if json_mode:
            corps["response_format"] = {"type": "json_object"}
        derniere = ""
        for essai in range(tentatives):
            try:
                code, data = _http("POST", f"{self.base}/chat/completions", corps,
                                   entetes={"Authorization": f"Bearer {self.cle}"},
                                   timeout=180, tentatives=1)
            except ErreurOrchestrateur as e:
                derniere = str(e)
                time.sleep(2.0 * (essai + 1))
                continue
            if code == 200 and isinstance(data, dict):
                choix = (data.get("choices") or [{}])[0]
                texte = ((choix.get("message") or {}).get("content") or "").strip()
                usage = data.get("usage") or {}
                with self._verrou:
                    self._appels += 1
                    self._jetons += int(usage.get("total_tokens") or 0)
                    self.derniere_finish = choix.get("finish_reason")
                    self.dernier_usage = usage
                if texte:
                    return texte
                derniere = "reponse vide du modele"
            else:
                derniere = f"HTTP {code} : {str(data)[:300]}"
                if code in (401, 403):
                    break
            time.sleep(2.0 * (essai + 1))
        raise ErreurLLM(f"appel LLM echoue ({modele}) — {derniere}")

    def chat_json(self, messages: list[dict], **kw) -> dict:
        """Appel avec sortie JSON : tolere un bloc ```json ... ``` parasite."""
        brut = self.chat(messages, json_mode=True, **kw)
        return json_tolerant(brut)

    @property
    def statistiques(self) -> dict:
        return {"appels": self._appels, "jetons": self._jetons, "modele": self.modele}


def json_tolerant(brut: str) -> dict:
    """Extrait un objet JSON d'une reponse LLM (bloc markdown, texte autour)."""
    texte = (brut or "").strip()
    if texte.startswith("```"):
        texte = texte.split("```")[1] if len(texte.split("```")) > 1 else texte
        if texte.lstrip().lower().startswith("json"):
            texte = texte.lstrip()[4:]
    for candidat in (texte, texte[texte.find("{"): texte.rfind("}") + 1] if "{" in texte else ""):
        if not candidat:
            continue
        try:
            valeur = json.loads(candidat)
            if isinstance(valeur, dict):
                return valeur
        except ValueError:
            continue
    raise ValueError(f"reponse non-JSON du modele : {brut[:200]}")


# --------------------------------------------------------------------------- connaissances
@dataclass
class BaseConnaissances:
    """Fichiers de connaissance d'un agent, avec empreintes pour la tracabilite."""

    fichiers: list[str]
    textes: dict[str, str] = field(default_factory=dict)

    def charger(self, racine: Path | None = None) -> "BaseConnaissances":
        base = racine or (ROOT / "knowledge")
        for nom in self.fichiers:
            f = base / nom
            self.textes[nom] = f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""
        return self

    @property
    def empreintes(self) -> dict[str, dict]:
        return {nom: {"sha256": sha256(txt), "caracteres": len(txt)}
                for nom, txt in self.textes.items() if txt}

    @property
    def volume(self) -> int:
        return sum(len(t) for t in self.textes.values())

    def texte(self, limite_par_fichier: int = 40000) -> str:
        morceaux = []
        for nom, txt in self.textes.items():
            if not txt:
                continue
            extrait = txt[:limite_par_fichier]
            if len(txt) > limite_par_fichier:
                extrait += "\n[...base tronquee pour cet appel...]"
            morceaux.append(f"### Base de connaissances — {nom}\n{extrait}")
        return "\n\n".join(morceaux)

    def manquants(self) -> list[str]:
        return [nom for nom, txt in self.textes.items() if not txt]


# --------------------------------------------------------------------------- trace
@dataclass
class Trace:
    """Journal d'execution tracable : chaque etape, sa duree, son auteur, sa sortie."""

    demande: str
    dossier: Path
    etapes: list[dict] = field(default_factory=list)
    debut: float = field(default_factory=time.time)

    def ajoute(self, etape: str, acteur: str, detail: str = "", **extra: Any) -> dict:
        evt = {
            "n": len(self.etapes) + 1,
            "etape": etape,
            "acteur": acteur,
            "heure": horodate(),
            "ecoule_s": round(time.time() - self.debut, 2),
            "detail": detail,
            **extra,
        }
        self.etapes.append(evt)
        dire(etape, f"{acteur} — {detail}" if detail else acteur)
        return evt

    def ecrire(self, meta: dict | None = None) -> Path:
        chemin = self.dossier / "trace.json"
        contenu = {
            "service": SERVICE,
            "demande": self.demande,
            "debut": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duree_s": round(time.time() - self.debut, 2),
            "orchestrateur": ORCH,
            "meta": meta or {},
            "etapes": self.etapes,
        }
        chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")
        return chemin

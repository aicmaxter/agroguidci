"""conversations.py — fils de discussion de l'agent agronome (SQLite).

Séparation nette avec le journal de mission : ce module ne stocke que ce qui est
nécessaire à l'interface (question, réponse, statut, sources), jamais les journaux
du moteur, ni les traces d'outils, ni aucune clé.

Sécurité
    - le jeton de session n'est jamais stocké : seule son empreinte SHA-256 l'est ;
    - chaque lecture/écriture vérifie la propriété (conversation.session_id) ;
    - l'identifiant de conversation est aléatoire sur 128 bits (non devinable) ;
    - idempotence garantie par UNIQUE(conversation_id, idempotency_key).

Configuration
    AGRO_CONVERSATIONS_DB   chemin de la base (défaut : data/conversations.db)
    AGRO_CONV_TTL_JOURS     conservation d'une conversation (défaut : 90)
    AGRO_SESSION_JOURS      durée de session glissante (défaut : 30)
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CHEMIN = Path(os.environ.get("AGRO_CONVERSATIONS_DB") or (ROOT / "data" / "conversations.db"))
TTL_CONVERSATION_S = int(float(os.environ.get("AGRO_CONV_TTL_JOURS", "90") or 90) * 86400)
DUREE_SESSION_S = int(float(os.environ.get("AGRO_SESSION_JOURS", "30") or 30) * 86400)
MAX_MESSAGE = 2000
MAX_REPONSE = 4000       # une réponse d'agent dépasse la limite d'une question (plafond du schéma)
MAX_TOURS = 200          # garde-fou : une conversation ne peut pas grossir sans fin

# Quotas : valeurs proposées, volontairement NON appliquées (validation requise).
QUOTAS_PROPOSES = {
    "messages_par_session_heure": 20,
    "messages_par_ip_jour": 40,
    "conversations_actives_par_session": 5,
    "taille_max_message": MAX_MESSAGE,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id    TEXT PRIMARY KEY,
  token_hash    BLOB NOT NULL UNIQUE,
  created_at    INTEGER NOT NULL,
  last_seen_at  INTEGER NOT NULL,
  expires_at    INTEGER NOT NULL,
  revoked_at    INTEGER
);

CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  titre           TEXT,
  culture_id      TEXT,
  localite        TEXT,
  statut          TEXT NOT NULL DEFAULT 'active'
                  CHECK (statut IN ('active','archivee','expiree')),
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL,
  expires_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_conv_session ON conversations(session_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_conv_expire  ON conversations(expires_at);

CREATE TABLE IF NOT EXISTS messages (
  message_id      TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant','systeme')),
  contenu         TEXT NOT NULL CHECK (length(contenu) BETWEEN 1 AND 4000),
  statut          TEXT NOT NULL CHECK (statut IN
                  ('en_cours','termine','echec','info_insuffisante','clarification','escalade')),
  mission_id      TEXT,
  demande_id      TEXT,
  erreur          TEXT,
  sources_json    TEXT,
  idempotency_key TEXT,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL,
  UNIQUE (conversation_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_msg_conv    ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_msg_encours ON messages(statut) WHERE statut = 'en_cours';
CREATE INDEX IF NOT EXISTS ix_msg_mission ON messages(mission_id) WHERE mission_id IS NOT NULL;
"""

_connexion: sqlite3.Connection | None = None
_chemin_ouvert: str | None = None


def _db() -> sqlite3.Connection:
    """Connexion unique par processus (le moteur est mono-processus)."""
    global _connexion, _chemin_ouvert
    if _connexion is not None and _chemin_ouvert == str(CHEMIN):
        return _connexion
    CHEMIN.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHEMIN), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    _connexion, _chemin_ouvert = conn, str(CHEMIN)
    return conn


def _hacher(jeton: str) -> bytes:
    return hashlib.sha256(jeton.encode("utf-8")).digest()


# ------------------------------------------------------------------ sessions
def creer_session() -> dict[str, Any]:
    """Crée une session anonyme. Le jeton en clair n'est rendu qu'une fois."""
    jeton = secrets.token_urlsafe(32)
    now = int(time.time())
    sid = "ses_" + uuid.uuid4().hex
    c = _db()
    c.execute("INSERT INTO sessions(session_id, token_hash, created_at, last_seen_at, expires_at) VALUES(?,?,?,?,?)",
              (sid, _hacher(jeton), now, now, now + DUREE_SESSION_S))
    c.commit()
    return {"session_id": sid, "session_token": jeton, "expires_at": now + DUREE_SESSION_S}


def session_valide(jeton: str | None) -> str | None:
    """Renvoie l'identifiant de session si le jeton est valide et non expiré."""
    if not jeton or len(jeton) > 200:
        return None
    c = _db()
    row = c.execute("SELECT session_id, expires_at, revoked_at FROM sessions WHERE token_hash=?",
                    (_hacher(jeton),)).fetchone()
    if not row or row["revoked_at"]:
        return None
    now = int(time.time())
    if row["expires_at"] < now:
        return None
    c.execute("UPDATE sessions SET last_seen_at=?, expires_at=? WHERE session_id=?",
              (now, now + DUREE_SESSION_S, row["session_id"]))
    c.commit()
    return row["session_id"]


# ------------------------------------------------------------- conversations
def creer_conversation(session_id: str, culture_id: str | None = None,
                       localite: str | None = None) -> dict[str, Any]:
    now = int(time.time())
    cid = "cnv_" + secrets.token_hex(16)          # 128 bits
    c = _db()
    c.execute("""INSERT INTO conversations(conversation_id, session_id, culture_id, localite,
                 statut, created_at, updated_at, expires_at) VALUES(?,?,?,?,'active',?,?,?)""",
              (cid, session_id, (culture_id or "")[:60] or None, (localite or "")[:120] or None,
               now, now, now + TTL_CONVERSATION_S))
    c.commit()
    return {"conversation_id": cid, "expires_at": now + TTL_CONVERSATION_S}


def conversation_de(session_id: str, conversation_id: str) -> sqlite3.Row | None:
    """Propriété vérifiée : renvoie None si la conversation n'est pas celle de la session."""
    return _db().execute(
        "SELECT * FROM conversations WHERE conversation_id=? AND session_id=?",
        (conversation_id, session_id)).fetchone()


def ajouter_message(conversation_id: str, role: str, contenu: str, statut: str = "en_cours",
                    idempotency_key: str | None = None, mission_id: str | None = None,
                    demande_id: str | None = None, erreur: str | None = None,
                    sources: list | None = None) -> dict[str, Any]:
    """Ajoute un message. Si la clé d'idempotence existe déjà, renvoie l'existant."""
    contenu = (contenu or "").strip()
    if not contenu:
        raise ValueError("message vide")
    # Une question est bornée à MAX_MESSAGE ; une réponse d'agent peut être plus longue.
    limite = MAX_REPONSE if role == "assistant" else MAX_MESSAGE
    if len(contenu) > limite:
        raise ValueError(f"message trop long ({len(contenu)} > {limite})")
    c = _db()
    if idempotency_key:
        deja = c.execute(
            "SELECT * FROM messages WHERE conversation_id=? AND idempotency_key=?",
            (conversation_id, idempotency_key)).fetchone()
        if deja:
            return dict(deja) | {"rejoue": True}
    tours = c.execute("SELECT COUNT(*) n FROM messages WHERE conversation_id=?",
                      (conversation_id,)).fetchone()["n"]
    if tours >= MAX_TOURS:
        raise ValueError("conversation trop longue")

    now = int(time.time())
    mid = "msg_" + uuid.uuid4().hex
    c.execute("""INSERT INTO messages(message_id, conversation_id, role, contenu, statut,
                 mission_id, demande_id, erreur, sources_json, idempotency_key, created_at, updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (mid, conversation_id, role, contenu, statut, mission_id, demande_id, erreur,
               json.dumps(sources, ensure_ascii=False) if sources else None, idempotency_key, now, now))
    c.execute("UPDATE conversations SET updated_at=? WHERE conversation_id=?", (now, conversation_id))
    c.commit()
    return dict(c.execute("SELECT * FROM messages WHERE message_id=?", (mid,)).fetchone()) | {"rejoue": False}


def maj_message(message_id: str, **champs: Any) -> None:
    autorises = {"statut", "contenu", "mission_id", "demande_id", "erreur", "sources_json"}
    champs = {k: v for k, v in champs.items() if k in autorises}
    if not champs:
        return
    champs["updated_at"] = int(time.time())
    sets = ", ".join(f"{k}=?" for k in champs)
    c = _db()
    c.execute(f"UPDATE messages SET {sets} WHERE message_id=?", (*champs.values(), message_id))
    c.commit()


def repondre(conversation_id: str, message_id: str, contenu: str, statut: str,
             mission_id: str | None = None, sources: list | None = None,
             erreur: str | None = None, assistant_id: str | None = None) -> dict[str, Any]:
    """Clôt la question et publie la réponse de l'agent.

    `assistant_id` : identifiant d'un message d'avancement déjà publié dans le fil
    (extrait réel pendant la rédaction). Il est alors MIS À JOUR au lieu d'ajouter
    une seconde bulle : un seul message d'agent par question.
    """
    contenu = (contenu or "").strip() or "Aucune réponse exploitable n'a été produite."
    sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
    maj_message(message_id, statut=statut, mission_id=mission_id, erreur=erreur,
                sources_json=sources_json)
    if assistant_id:
        maj_message(assistant_id, contenu=contenu, statut=statut, mission_id=mission_id,
                    sources_json=sources_json)
        return {"message_id": assistant_id, "rejoue": True}
    return ajouter_message(conversation_id, "assistant", contenu, statut=statut,
                           mission_id=mission_id, sources=sources)


def fil(session_id: str, conversation_id: str) -> dict[str, Any] | None:
    """Historique complet, uniquement si la conversation appartient à la session."""
    conv = conversation_de(session_id, conversation_id)
    if not conv:
        return None
    c = _db()
    msgs = c.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at, rowid",
                     (conversation_id,)).fetchall()
    return {
        "conversation_id": conv["conversation_id"],
        "culture_id": conv["culture_id"],
        "localite": conv["localite"],
        "statut": conv["statut"],
        "cree_le": conv["created_at"],
        "expire_le": conv["expires_at"],
        "messages": [
            {"message_id": m["message_id"], "role": m["role"], "contenu": m["contenu"],
             "statut": m["statut"], "mission_id": m["mission_id"],
             "erreur": m["erreur"],
             "sources": json.loads(m["sources_json"]) if m["sources_json"] else [],
             "cree_le": m["created_at"]}
            for m in msgs
        ],
    }


def purger_expire(limite: int = 500) -> dict[str, int]:
    """Supprime les conversations expirées (cascade sur les messages). Retourne les compteurs."""
    now = int(time.time())
    c = _db()
    ids = [r["conversation_id"] for r in c.execute(
        "SELECT conversation_id FROM conversations WHERE expires_at < ? LIMIT ?", (now, limite))]
    if ids:
        c.executemany("DELETE FROM conversations WHERE conversation_id=?", [(i,) for i in ids])
    sessions = c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,)).rowcount
    c.commit()
    return {"conversations": len(ids), "sessions": max(0, sessions)}


def purger_wal() -> None:
    """Compacte la base après une purge (appel manuel, jamais dans une requête)."""
    c = _db()
    c.execute("PRAGMA incremental_vacuum")
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.commit()

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
LIMITE_CONTENU = 12000   # plafond du schéma : une réponse d'agent (synthèse) tient entière
MAX_REPONSE = LIMITE_CONTENU
MAX_TOURS = 200          # garde-fou : une conversation ne peut pas grossir sans fin
VERSION_SCHEMA = 3       # 3 : validation humaine (auto/relu/valide) et niveau de risque

# ---------------------------------------------------------------- crédits
# 15 crédits gratuits par fenêtre de 7 h, renouvelés automatiquement au passage de
# fenêtre (comportement retenu : l'ancien quota se remettait déjà à zéro sans action
# de l'utilisateur). Calcul en UTC, idempotent par (session, période).
CREDITS_GRATUITS = int(os.environ.get("AGRO_CREDITS_GRATUITS", "15") or 15)
PERIODE_CREDITS_S = int(float(os.environ.get("AGRO_CREDITS_PERIODE_H", "7") or 7) * 3600)
COUT_CONSULTATION = int(os.environ.get("AGRO_CREDITS_COUT", "1") or 1)
MAX_CREDITS_ACHAT = 100000   # garde-fou de saisie, jamais atteint par les packs publics


# Quotas : valeurs proposées, volontairement NON appliquées (validation requise).
QUOTAS_PROPOSES = {
    "messages_par_session_heure": 20,
    "messages_par_ip_jour": 40,
    "conversations_actives_par_session": 5,
    "taille_max_message": MAX_MESSAGE,
}

_DDL_MESSAGES = """
CREATE TABLE {ifnot}{table} (
  message_id      TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant','systeme')),
  contenu         TEXT NOT NULL CHECK (length(contenu) BETWEEN 1 AND {limite}),
  statut          TEXT NOT NULL CHECK (statut IN
                  ('en_cours','termine','echec','info_insuffisante','clarification','escalade')),
  mission_id      TEXT,
  demande_id      TEXT,
  erreur          TEXT,
  sources_json    TEXT,
  validation      TEXT NOT NULL DEFAULT 'auto'
                  CHECK (validation IN ('auto','relu','valide')),
  validateur      TEXT,
  valide_le       INTEGER,
  risque          TEXT CHECK (risque IN ('faible','modere','eleve')),
  idempotency_key TEXT,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL,
  UNIQUE (conversation_id, idempotency_key)
);
"""

_INDEX_MESSAGES = """
CREATE INDEX IF NOT EXISTS ix_msg_conv    ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_msg_encours ON messages(statut) WHERE statut = 'en_cours';
CREATE INDEX IF NOT EXISTS ix_msg_mission ON messages(mission_id) WHERE mission_id IS NOT NULL;
"""

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

-- Journal des mouvements de crédits : la seule source de vérité du solde.
-- 'gratuit' : lot de la fenêtre courante (periode = index de fenêtre UTC) ;
-- 'achete'  : crédits payés, sans expiration, consommés après les gratuits.
CREATE TABLE IF NOT EXISTS credits (
  credit_id   TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  bucket      TEXT NOT NULL CHECK (bucket IN ('gratuit','achete')),
  delta       INTEGER NOT NULL,
  raison      TEXT NOT NULL,
  reference   TEXT,
  periode     INTEGER,
  created_at  INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_credits_lot
  ON credits(session_id, periode) WHERE raison = 'gratuit_periode';
CREATE UNIQUE INDEX IF NOT EXISTS ux_credits_debit
  ON credits(session_id, reference) WHERE raison = 'consultation';
CREATE INDEX IF NOT EXISTS ix_credits_session ON credits(session_id, created_at);
""" + _DDL_MESSAGES.format(ifnot="IF NOT EXISTS ", table="messages", limite=LIMITE_CONTENU) + _INDEX_MESSAGES

_connexion: sqlite3.Connection | None = None
_chemin_ouvert: str | None = None


def _migrer(conn: sqlite3.Connection) -> None:
    """Migrations de schéma, idempotentes (PRAGMA user_version).

    2 : la limite de longueur d'un message passe de 4000 à LIMITE_CONTENU. Les
        réponses de l'agent (synthèse de plusieurs volets) étaient tronquées.
        SQLite ne sait pas modifier un CHECK : on reconstruit la table en
        conservant toutes les lignes, puis on recrée index et version.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= VERSION_SCHEMA:
        return
    ligne = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
                         ).fetchone()
    ddl = (ligne[0] or "") if ligne else ""
    if ddl and f"BETWEEN 1 AND {LIMITE_CONTENU}" not in ddl:
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.executescript(
                "BEGIN;DROP TABLE IF EXISTS messages_v2;"
                + _DDL_MESSAGES.format(ifnot="", table="messages_v2", limite=LIMITE_CONTENU)
                + "INSERT INTO messages_v2 (message_id, conversation_id, role, contenu, statut,"
                + " mission_id, demande_id, erreur, sources_json, idempotency_key, created_at, updated_at)"
                + " SELECT message_id, conversation_id, role, contenu, statut, mission_id, demande_id,"
                + " erreur, sources_json, idempotency_key, created_at, updated_at FROM messages;"
                + "DROP TABLE messages;"
                + "ALTER TABLE messages_v2 RENAME TO messages;" + _INDEX_MESSAGES + "COMMIT;")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
    # 3 : validation humaine (auto/relu/valide), validateur et niveau de risque.
    #     ALTER TABLE ADD COLUMN est additif : aucune ligne n'est perdue.
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    for nom, typ in {
        "validation": "TEXT NOT NULL DEFAULT 'auto'",
        "validateur": "TEXT",
        "valide_le": "INTEGER",
        "risque": "TEXT",
    }.items():
        if nom not in colonnes:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {nom} {typ}")

    conn.execute(f"PRAGMA user_version={VERSION_SCHEMA}")
    conn.commit()


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
    _migrer(conn)               # schéma d'une base existante : voir VERSION_SCHEMA
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
    autorises = {"statut", "contenu", "mission_id", "demande_id", "erreur", "sources_json",
                 "risque", "validation", "validateur", "valide_le"}
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
             erreur: str | None = None, assistant_id: str | None = None,
             risque: str | None = None) -> dict[str, Any]:
    """Clôt la question et publie la réponse de l'agent.

    `assistant_id` : identifiant d'un message d'avancement déjà publié dans le fil
    (extrait réel pendant la rédaction). Il est alors MIS À JOUR au lieu d'ajouter
    une seconde bulle : un seul message d'agent par question.
    """
    contenu = (contenu or "").strip() or "Aucune réponse exploitable n'a été produite."
    sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
    maj_message(message_id, statut=statut, mission_id=mission_id, erreur=erreur,
                sources_json=sources_json, risque=risque)
    if assistant_id:
        maj_message(assistant_id, contenu=contenu, statut=statut, mission_id=mission_id,
                    sources_json=sources_json, risque=risque)
        return {"message_id": assistant_id, "rejoue": True}
    m = ajouter_message(conversation_id, "assistant", contenu, statut=statut,
                        mission_id=mission_id, sources=sources)
    if risque:
        maj_message(m["message_id"], risque=risque)
    return m


def valider_message(conversation_id: str, message_id: str, statut: str, validateur: str) -> dict[str, Any] | None:
    """Trace une relecture humaine : statut 'relu' ou 'valide' uniquement.

    Aucune réponse ne peut être présentée comme validée sans cet appel : le statut
    par défaut reste 'auto' (réponse générée automatiquement).
    """
    if statut not in ("relu", "valide"):
        raise ValueError("statut de validation invalide")
    validateur = (validateur or "").strip()
    if len(validateur) < 3 or len(validateur) > 120:
        raise ValueError("identifiant de validateur invalide")
    c = _db()
    row = c.execute("SELECT message_id FROM messages WHERE message_id=? AND conversation_id=? AND role='assistant'",
                    (message_id, conversation_id)).fetchone()
    if not row:
        return None
    c.execute("UPDATE messages SET validation=?, validateur=?, valide_le=?, updated_at=? WHERE message_id=?",
              (statut, validateur, int(time.time()), int(time.time()), message_id))
    c.commit()
    m = c.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
    return {"message_id": m["message_id"], "validation": m["validation"],
            "validateur": m["validateur"], "valide_le": m["valide_le"]}


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
             "validation": m["validation"] if "validation" in m.keys() else "auto",
             "validateur": m["validateur"] if "validateur" in m.keys() else None,
             "valide_le": m["valide_le"] if "valide_le" in m.keys() else None,
             "risque": m["risque"] if "risque" in m.keys() else None,
             "cree_le": m["created_at"]}
            for m in msgs
        ],
    }


def periode_courante(now: int | None = None) -> int:
    """Index de la fenêtre de crédits gratuits (UTC, 7 h par défaut)."""
    return int((now if now is not None else time.time()) // PERIODE_CREDITS_S)


def _lot_gratuit(session_id: str, now: int) -> int:
    """Attribue le lot gratuit de la fenêtre courante — idempotent.

    L'index unique partiel `(session_id, periode) WHERE raison='gratuit_periode'`
    garantit qu'une même fenêtre ne peut pas être créditée deux fois, même sous
    requêtes simultanées : le second INSERT est ignoré.
    """
    periode = periode_courante(now)
    c = _db()
    c.execute(
        "INSERT OR IGNORE INTO credits(credit_id, session_id, bucket, delta, raison, reference, periode, created_at) "
        "VALUES(?, ?, 'gratuit', ?, 'gratuit_periode', NULL, ?, ?)",
        ("crt_" + uuid.uuid4().hex, session_id, CREDITS_GRATUITS, periode, now))
    c.commit()
    return periode


def solde(session_id: str, now: int | None = None) -> dict[str, Any]:
    """Solde réel calculé depuis le journal des mouvements (jamais depuis le navigateur)."""
    now = int(now if now is not None else time.time())
    periode = _lot_gratuit(session_id, now)
    c = _db()
    gratuits = c.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM credits WHERE session_id=? AND bucket='gratuit' AND periode=?",
        (session_id, periode)).fetchone()[0] or 0
    achetes = c.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM credits WHERE session_id=? AND bucket='achete'",
        (session_id,)).fetchone()[0] or 0
    gratuits, achetes = max(0, gratuits), max(0, achetes)
    fin = (periode + 1) * PERIODE_CREDITS_S
    return {
        "gratuits": gratuits,
        "achetes": achetes,
        "total": gratuits + achetes,
        "lot_gratuit": CREDITS_GRATUITS,
        "periode_heures": round(PERIODE_CREDITS_S / 3600, 2),
        "periode": periode,
        "periode_debut": periode * PERIODE_CREDITS_S,
        "renouvellement_at": fin,
        "secondes_avant_renouvellement": max(0, fin - now),
        "cout_consultation": COUT_CONSULTATION,
        "serveur_maintenant": now,
    }


def deja_debite(session_id: str, reference: str) -> bool:
    """Vrai si cette référence (message_id) a déjà été débitée."""
    row = _db().execute(
        "SELECT 1 FROM credits WHERE session_id=? AND reference=? AND raison='consultation'",
        (session_id, reference)).fetchone()
    return bool(row)


def consommer(session_id: str, reference: str, cout: int | None = None) -> dict[str, Any] | None:
    """Débite une consultation. Renvoie le solde, ou None si le solde est insuffisant.

    - un seul débit par `reference` (contrainte UNIQUE partielle) : un renvoi de la
      même requête ne peut pas débiter deux fois ;
    - le débit est conditionné, dans la requête SQL elle-même, à un solde suffisant :
      le solde ne peut pas devenir négatif ;
    - les crédits gratuits de la fenêtre sont consommés avant les crédits achetés.
    """
    cout = COUT_CONSULTATION if cout is None else max(1, int(cout))
    now = int(time.time())
    periode = _lot_gratuit(session_id, now)
    c = _db()
    if deja_debite(session_id, reference):
        return solde(session_id, now)
    for bucket, garde in (
        ("gratuit", "SELECT COALESCE(SUM(delta),0) FROM credits WHERE session_id=? AND bucket='gratuit' AND periode=?"),
        ("achete", "SELECT COALESCE(SUM(delta),0) FROM credits WHERE session_id=? AND bucket='achete'"),
    ):
        params_garde = (session_id, periode) if bucket == "gratuit" else (session_id,)
        insere = c.execute(
            "INSERT INTO credits(credit_id, session_id, bucket, delta, raison, reference, periode, created_at) "
            "SELECT ?, ?, ?, ?, 'consultation', ?, ?, ? WHERE (" + garde + ") >= ?",
            ("crt_" + uuid.uuid4().hex, session_id, bucket, -cout, reference, periode, now,
             *params_garde, cout)).rowcount
        c.commit()
        if insere:
            return solde(session_id, now)
    return None


def historique(session_id: str, limite: int = 50) -> list[dict[str, Any]]:
    """Mouvements récents (trace auditable : jamais de donnée de paiement ici)."""
    rows = _db().execute(
        "SELECT bucket, delta, raison, reference, periode, created_at FROM credits "
        "WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (session_id, max(1, min(200, int(limite))))).fetchall()
    return [dict(r) for r in rows]


def ajouter_credits_achetes(session_id: str, quantite: int, reference: str) -> dict[str, Any]:
    """Crédite un achat CONFIRMÉ (appelé uniquement par un webhook vérifié).

    Idempotent : la même référence de paiement ne crédite qu'une fois.
    """
    quantite = int(quantite)
    if quantite <= 0 or quantite > MAX_CREDITS_ACHAT:
        raise ValueError("quantité de crédits invalide")
    now = int(time.time())
    c = _db()
    if c.execute("SELECT 1 FROM credits WHERE session_id=? AND reference=? AND raison='achat'",
                 (session_id, reference)).fetchone():
        return solde(session_id, now)
    c.execute(
        "INSERT INTO credits(credit_id, session_id, bucket, delta, raison, reference, periode, created_at) "
        "VALUES(?, ?, 'achete', ?, 'achat', ?, NULL, ?)",
        ("crt_" + uuid.uuid4().hex, session_id, quantite, reference, now))
    c.commit()
    return solde(session_id, now)


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

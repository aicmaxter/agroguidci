"""purge_conversations.py — supprime les conversations expirées (90 jours par défaut).

    python scripts/purge_conversations.py              # simulation (aucune écriture)
    python scripts/purge_conversations.py --appliquer  # purge réelle + sauvegarde préalable

La base est celle du moteur (variable AGRO_CONVERSATIONS_DB, par défaut data/conversations.db).
Une sauvegarde horodatée est créée avant toute suppression réelle (VACUUM INTO).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Purge des conversations expirées")
    p.add_argument("--appliquer", action="store_true", help="exécuter réellement la purge")
    p.add_argument("--base", default=os.environ.get("AGRO_CONVERSATIONS_DB") or str(ROOT / "data" / "conversations.db"))
    a = p.parse_args()

    base = Path(a.base)
    if not base.exists():
        print(f"Base absente : {base}")
        return 1

    conn = sqlite3.connect(str(base), timeout=10)
    conn.row_factory = sqlite3.Row
    now = int(time.time())
    conv = conn.execute("SELECT COUNT(*) n FROM conversations WHERE expires_at < ?", (now,)).fetchone()["n"]
    msgs = conn.execute(
        "SELECT COUNT(*) n FROM messages WHERE conversation_id IN "
        "(SELECT conversation_id FROM conversations WHERE expires_at < ?)", (now,)).fetchone()["n"]
    ses = conn.execute("SELECT COUNT(*) n FROM sessions WHERE expires_at < ?", (now,)).fetchone()["n"]
    print(f"Base : {base}")
    print(f"À purger : {conv} conversation(s), {msgs} message(s), {ses} session(s) expirée(s)")

    if not a.appliquer:
        print("Simulation : rien n'a été supprimé. Relancer avec --appliquer.")
        conn.close()
        return 0

    sauvegarde = base.with_name(f"{base.stem}-avant-purge-{time.strftime('%Y%m%d-%H%M%S')}.db")
    conn.execute("VACUUM INTO ?", (str(sauvegarde),))
    print(f"Sauvegarde : {sauvegarde}")

    conn.execute("DELETE FROM conversations WHERE expires_at < ?", (now,))
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA incremental_vacuum")
    conn.commit()
    conn.close()
    print(f"Purge effectuée : {conv} conversation(s), {ses} session(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

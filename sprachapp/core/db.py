from __future__ import annotations

import os
import json
import sqlite3
from pathlib import Path
from typing import Any

# -------------------------------------------------------------------
# Datenbank-Pfad (ZENTRAL, NUR HIER DEFINIERT)
# -------------------------------------------------------------------
DB_PATH = Path(os.getenv("SPRACHAPP_DB", "data/sprachapp.sqlite3"))


# -------------------------------------------------------------------
# Connection Helper
# -------------------------------------------------------------------
def get_con() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


# -------------------------------------------------------------------
# DB Initialisierung
# -------------------------------------------------------------------
def ensure_db() -> None:
    con = get_con()
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            topic TEXT,
            mode TEXT,
            source_text TEXT,
            transcript TEXT,
            stats_payload TEXT,
            audio_path TEXT
        );
        """
    )

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode);"
    )

    con.commit()
    con.close()


# -------------------------------------------------------------------
# Insert Session
# -------------------------------------------------------------------
def insert_session(
    *,
    topic: str | None,
    mode: str,
    source_text: str | None,
    transcript: str,
    stats_payload: dict[str, Any],
    audio_path: str | None,
    created_at: str | None = None,
) -> int:
    # created_at immer setzen (sonst wird es in der DB oft leer/NULL)
    if created_at is None:
        from datetime import datetime, UTC
        created_at = datetime.now(UTC).isoformat()

    con = get_con()
    cur = con.cursor()

    cur.execute(
        """
        INSERT INTO sessions (
            created_at,
            topic,
            mode,
            source_text,
            transcript,
            stats_payload,
            audio_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            topic,
            mode,
            source_text,
            transcript,
            json.dumps(stats_payload, ensure_ascii=False),
            audio_path,
        ),
    )

    session_id = cur.lastrowid
    con.commit()
    con.close()
    return int(session_id)
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

    # --- sessions (bestehend) ---
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode);")

    # --- vocab (neu, MVP7 / Define-Vocab) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL UNIQUE,
            lang TEXT NOT NULL DEFAULT 'de',
            difficulty TEXT NOT NULL DEFAULT 'medium',
            definition_text TEXT NOT NULL,
            example_1 TEXT,
            example_2 TEXT,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_practiced_at TEXT,
            practice_count INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vocab_term ON vocab(term);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vocab_last_practiced ON vocab(last_practiced_at);")

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


# -------------------------------------------------------------------
# Vocab (MVP7 / Define-Vocab) – minimaler DB-Layer
# -------------------------------------------------------------------
def add_vocab(
    *,
    term: str,
    definition_text: str,
    difficulty: str = "medium",
    lang: str = "de",
    example_1: str | None = None,
    example_2: str | None = None,
    source: str | None = "manual",
) -> int:
    """
    Legt eine Vokabel an (oder aktualisiert sie, falls term bereits existiert).
    Hints werden NICHT gespeichert (werden jedes Mal neu generiert).
    """
    from datetime import datetime, UTC

    now = datetime.now(UTC).isoformat()
    term = term.strip()
    definition_text = definition_text.strip()

    con = get_con()
    cur = con.cursor()

    # UPSERT per UNIQUE(term)
    cur.execute(
        """
        INSERT INTO vocab (
            term, lang, difficulty, definition_text,
            example_1, example_2, source,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(term) DO UPDATE SET
            lang=excluded.lang,
            difficulty=excluded.difficulty,
            definition_text=excluded.definition_text,
            example_1=excluded.example_1,
            example_2=excluded.example_2,
            source=excluded.source,
            updated_at=excluded.updated_at
        """,
        (
            term,
            lang,
            difficulty,
            definition_text,
            example_1,
            example_2,
            source,
            now,
            now,
        ),
    )

    vocab_id = cur.execute("SELECT id FROM vocab WHERE term = ?", (term,)).fetchone()[0]
    con.commit()
    con.close()
    return int(vocab_id)


def list_vocab_alpha() -> list[dict[str, Any]]:
    """Liste aller Vokabeln alphabetisch nach term."""
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    rows = cur.execute(
        """
        SELECT
            id, term, lang, difficulty, definition_text,
            example_1, example_2, source,
            created_at, updated_at, last_practiced_at, practice_count
        FROM vocab
        ORDER BY term COLLATE NOCASE ASC
        """
    ).fetchall()

    con.close()
    return [dict(r) for r in rows]


def get_vocab_by_term(term: str) -> dict | None:
    """Hole eine Vokabel gezielt nach Begriff."""
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    row = cur.execute(
        """
        SELECT
            id, term, lang, difficulty, definition_text,
            example_1, example_2, source,
            created_at, updated_at, last_practiced_at, practice_count
        FROM vocab
        WHERE term = ?
        """,
        (term.strip(),),
    ).fetchone()

    con.close()
    return dict(row) if row else None


def get_vocab_random() -> dict | None:
    """
    Hole eine zufällige Vokabel mit einfacher Priorisierung:
    - zuerst ungeübte (last_practiced_at IS NULL),
    - sonst die am längsten nicht geübten,
    - bei Gleichstand zufällig.
    """
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    row = cur.execute(
        """
        SELECT
            id, term, lang, difficulty, definition_text,
            example_1, example_2, source,
            created_at, updated_at, last_practiced_at, practice_count
        FROM vocab
        ORDER BY
            (last_practiced_at IS NOT NULL) ASC,  -- NULL zuerst
            last_practiced_at ASC,                -- älteste zuerst
            RANDOM()
        LIMIT 1
        """
    ).fetchone()

    con.close()
    return dict(row) if row else None


def mark_vocab_practiced(vocab_id: int) -> None:
    """Increment practice_count and set last_practiced_at/updated_at to now."""
    from datetime import datetime, UTC

    now = datetime.now(UTC).isoformat()

    con = get_con()
    cur = con.cursor()
    cur.execute(
        """
        UPDATE vocab
        SET
            practice_count = practice_count + 1,
            last_practiced_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (now, now, int(vocab_id)),
    )
    con.commit()
    con.close()




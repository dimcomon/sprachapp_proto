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

    # --- learning path templates (MVP7 - Struktur) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_path_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            level TEXT NOT NULL,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_path_template_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            step_order INTEGER NOT NULL,
            step_type TEXT NOT NULL,        -- news | define_vocab | review
            config TEXT,                    -- JSON als Text (Parameter)
            FOREIGN KEY(template_id) REFERENCES learning_path_templates(id)
        );
        """
    )
    
    # --- sessions v2 (MVP7 - Struktur) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            step_order INTEGER NOT NULL,
            step_type TEXT NOT NULL,        -- news | define_vocab | review
            content_ref TEXT,               -- z. B. news_id, vocab_id (Text/JSON)
            status TEXT NOT NULL DEFAULT 'open',
            started_at TEXT NOT NULL,
            completed_at TEXT
        );
        """
    )

    # sessions_v2: text_id nachrüsten (falls fehlt)
    cols = [r[1] for r in cur.execute("PRAGMA table_info(sessions_v2);").fetchall()]
    if "text_id" not in cols:
        cur.execute("ALTER TABLE sessions_v2 ADD COLUMN text_id INTEGER;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_v2_text_id ON sessions_v2(text_id);")

    # --- texts (MVP7) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS texts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,      -- news | book
            title TEXT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_texts_source_type ON texts(source_type);")
    # --- session_vocab (MVP7) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS session_vocab (
            session_id INTEGER NOT NULL,
            vocab_id INTEGER NOT NULL,
            PRIMARY KEY (session_id, vocab_id),
            FOREIGN KEY(session_id) REFERENCES sessions_v2(id),
            FOREIGN KEY(vocab_id) REFERENCES vocab(id)
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_session_vocab_session ON session_vocab(session_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_session_vocab_vocab ON session_vocab(vocab_id);")

    # --- learning path runs (MVP7) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_path_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',   -- active | completed | aborted
            started_at TEXT NOT NULL,
            completed_at TEXT
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lpr_template_id ON learning_path_runs(template_id);")

    # sessions_v2: run_id nachrüsten (falls fehlt)
    cols = [r[1] for r in cur.execute("PRAGMA table_info(sessions_v2);").fetchall()]
    if "run_id" not in cols:
        cur.execute("ALTER TABLE sessions_v2 ADD COLUMN run_id INTEGER;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_v2_run_id ON sessions_v2(run_id);")

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


def add_vocab(term: str, lang: str, difficulty: str, definition_text: str) -> int:
    """
    Speichert eine Vokabel und gibt ihre ID zurück.
    Wenn der Begriff schon existiert, wird keine neue Zeile erzeugt,
    sondern die existierende ID zurückgegeben.
    """
    from datetime import datetime, UTC

    now = datetime.now(UTC).isoformat()

    con = get_con()
    cur = con.cursor()

    # 1) Falls schon vorhanden -> ID zurückgeben
    row = cur.execute(
        "SELECT id FROM vocab WHERE term = ?",
        (term,),
    ).fetchone()
    if row:
        con.close()
        return int(row[0])

    # 2) Sonst neu anlegen -> ID zurückgeben
    cur.execute(
        """
        INSERT INTO vocab
            (term, lang, difficulty, definition_text, created_at, updated_at, last_practiced_at, practice_count)
        VALUES
            (?, ?, ?, ?, ?, ?, NULL, 0)
        """,
        (term, lang, difficulty, definition_text, now, now),
    )
    vid = cur.lastrowid
    con.commit()
    con.close()
    return int(vid)


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


def create_session_v2(
    *,
    template_id: int,
    step_order: int,
    step_type: str,
    content_ref: str | None = None,
    text_id: int | None = None,
    run_id: int | None = None,
    started_at: str | None = None,
) -> int:
    """Legt eine neue Session (open) an und gibt die Session-ID zurück."""
    from datetime import datetime, UTC

    if started_at is None:
        started_at = datetime.now(UTC).isoformat()

    con = get_con()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO sessions_v2
        (template_id, step_order, step_type, content_ref, text_id, run_id, status, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, NULL)
        """,
        (int(template_id), int(step_order), step_type, content_ref, text_id, run_id, started_at),
    )
    sid = cur.lastrowid
    con.commit()
    con.close()
    return int(sid)


def list_sessions_v2(*, status: str | None = "open") -> list[dict]:
    """Listet Sessions (default: open) nach Zeit sortiert."""
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if status is None:
        rows = cur.execute(
            """
            SELECT *
            FROM sessions_v2
            ORDER BY started_at DESC
            """
        ).fetchall()
    else:
        rows = cur.execute(
            """
            SELECT *
            FROM sessions_v2
            WHERE status = ?
            ORDER BY started_at DESC
            """,
            (status,),
        ).fetchall()

    con.close()
    return [dict(r) for r in rows]


def complete_session_v2(session_id: int) -> None:
    """Setzt eine Session auf completed und schreibt completed_at."""
    from datetime import datetime, UTC

    now = datetime.now(UTC).isoformat()

    con = get_con()
    cur = con.cursor()
    cur.execute(
        """
        UPDATE sessions_v2
        SET status = 'completed',
            completed_at = ?
        WHERE id = ?
        """,
        (now, int(session_id)),
    )
    con.commit()
    con.close()


def insert_text(source_type: str, title: str | None, content: str) -> int:
    """Speichert einen Text (news/book) und gibt die text_id zurück."""
    from datetime import datetime, UTC

    now = datetime.now(UTC).isoformat()

    con = get_con()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO texts (source_type, title, content, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (source_type, title, content, now),
    )
    tid = cur.lastrowid
    con.commit()
    con.close()
    return int(tid)


def link_session_vocab(session_id: int, vocab_id: int) -> None:
    """Verknüpft eine Session mit einer Vokabel (idempotent über PRIMARY KEY)."""
    con = get_con()
    cur = con.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO session_vocab (session_id, vocab_id)
        VALUES (?, ?)
        """,
        (int(session_id), int(vocab_id)),
    )
    con.commit()
    con.close()



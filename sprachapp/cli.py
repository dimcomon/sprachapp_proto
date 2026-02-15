from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sprachapp.core.db import (
    ensure_db,
    insert_session,
    add_vocab,
    list_vocab_alpha,
    get_vocab_by_term,
    get_vocab_random,
    mark_vocab_practiced,
    get_con,
    create_session_v2,
    list_sessions_v2,
    complete_session_v2,
    insert_text,
)
from sprachapp.core.audio import (
    list_input_devices, 
    record_mic_to_wav, 
    wav_duration_seconds, 
    cleanup_audio_retention,
)   
from sprachapp.core.asr import transcribe_with_whisper
from sprachapp.core.text import normalize_text, cut_at_punkt, overlap_metrics
from sprachapp.core.stats import compute_stats, suggest_target_terms, terms_used
from sprachapp.core.coach_backend_factory import get_coach_backend
from sprachapp.core.coach_backend import CoachRequest
from sprachapp.core.coach_print import print_coach_block

from sprachapp.modules.tutor_book import run_book_session
from sprachapp.modules.report import (
    fetch_last_sessions, 
    print_table, 
    write_csv, 
    print_summary, 
    print_progress,
)    
from sprachapp.modules.selfcheck import run_selfcheck
from sprachapp.modules.tutor_news import run_news_session
from sprachapp.modules._tutor_common import (
    compute_quality_flags, 
    print_quality_warnings,
)
from sprachapp.modules.tutor_define import run_define_session


def cmd_speak(args: argparse.Namespace) -> None:
    ensure_db()

    prompt_text = None
    if args.prompt_file:
        pf = Path(args.prompt_file)
        if not pf.exists():
            raise SystemExit(f"prompt-file nicht gefunden: {pf.resolve()}")
        prompt_text = pf.read_text(encoding="utf-8").strip()
        if prompt_text:
            args.source_text = prompt_text

    if args.record:
        from datetime import datetime, UTC
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out = Path("data/audio") / f"{ts}.wav"
        record_mic_to_wav(out_path=out, minutes=args.minutes, device=args.device)
        args.audio = str(out)

    if not args.audio:
        raise SystemExit("Kein --audio angegeben und --record nicht gesetzt.")

    p = Path(args.audio)
    if not p.exists():
        raise SystemExit(f"Audio-Datei nicht gefunden: {p.resolve()}")

    prev = None
    raw = transcribe_with_whisper(str(p))
    transcript = cut_at_punkt(raw) if args.cut_punkt else normalize_text(raw)

    stats = compute_stats(transcript)

    dur_s = None
    try:
        if p.suffix.lower() == ".wav":
            dur_s = wav_duration_seconds(p)
    except Exception:
        dur_s = None

    payload = stats.__dict__.copy()
    payload["duration_seconds"] = round(dur_s, 2) if dur_s else None
    payload["wpm"] = round(stats.word_count / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

    if args.source_text and args.mode == "read":
        payload["read_overlap"] = overlap_metrics(args.source_text, transcript)
        payload["read_similarity_note"] = "Similarity optional; LLM später"

    if args.source_text and args.mode == "retell":
        targets = suggest_target_terms(args.source_text, transcript, k=args.suggest_k)
        payload["target_terms"] = targets
        payload["target_terms_check"] = terms_used(targets, transcript)

    topic = args.topic or args.mode
    session_id = insert_session(
        topic=topic,
        mode=args.mode,
        source_text=args.source_text,
        transcript=transcript,
        stats_payload=payload,
        audio_path=str(p),
    )

    if args.delete_audio:
        try:
            p.unlink()
            print(f"Audio gelöscht: {p}")
        except Exception as e:
            print(f"Warnung: Konnte Audio nicht löschen: {e}")

    cleanup_audio_retention(Path("data/audio"), keep_last=args.keep_last_audios, keep_days=args.keep_days)

    print(f"\nSession gespeichert: id={session_id}")
    print(f"Transkription{' (gekürzt bis punkt)' if args.cut_punkt else ''}:\n{transcript}\n")
    print("Auswertung:", payload)

    if args.mode == "retell" and args.source_text and payload.get("target_terms"):
        print("\nNeue Ziel-Begriffe (für nächste Wiedergabe):")
        print(", ".join(payload["target_terms"]))

    if prev:
        print(f"\nLetzte Session war id={prev.get('id')} | mode={prev.get('mode')} | topic={prev.get('topic')}")


def cmd_define_vocab_add(args: argparse.Namespace) -> None:
    ensure_db()
    vid = add_vocab(
        term=args.term,
        definition_text=args.definition,
        difficulty=args.level,
        lang=args.lang,
        example_1=args.example1,
        example_2=args.example2,
        source=args.source,
    )
    print(f"Vokabel gespeichert: id={vid} | term={args.term}")


def cmd_define_vocab_list(args: argparse.Namespace) -> None:
    ensure_db()
    rows = list_vocab_alpha()

    if not rows:
        print("Keine Vokabeln gespeichert.")
        return

    print("\n--- VOCAB (alphabetisch) ---")
    for r in rows:
        term = r.get("term")
        level = r.get("difficulty")
        definition = r.get("definition_text")

        practiced = r.get("practice_count", 0)
        last = r.get("last_practiced_at") or "-"

        print(f"- {term} [{level}] (practiced={practiced}, last={last}) — {definition}")


# Focus q1
def cmd_focus_q1(args: argparse.Namespace) -> None:
    """
    Minimaler Fokus-Run: wiederholt q1 N-mal kurz hintereinander.
    - nutzt vorhandene Audio/ASR/Auswertung/Quality-Flags
    - speichert Einträge wie gewohnt
    - greift NICHT in book/news-progress ein
    """
    ensure_db()

    from datetime import datetime, UTC

    rounds = int(args.rounds)
    q_seconds = float(args.q_seconds)
    minutes = max(0.01, q_seconds / 60.0)

    print(f"FOKUS q1: {rounds} Runden á {int(q_seconds)}s")
    print("Aufgabe: Antworte als Q1 (These). Genau 1 Satz, ohne Wiederholung.\n")

    for i in range(1, rounds + 1):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out = Path("data/audio") / f"{ts}_focus-q1_r{i}.wav"

        print(f"--- Runde {i}/{rounds} ---")
        record_mic_to_wav(out_path=out, minutes=minutes, device=args.device)

        raw = transcribe_with_whisper(str(out))
        transcript = normalize_text(raw)

        stats = compute_stats(transcript)

        dur_s = None
        try:
            dur_s = wav_duration_seconds(out)
        except Exception:
            dur_s = None

        payload = stats.__dict__.copy()
        payload["duration_seconds"] = round(dur_s, 2) if dur_s else None
        payload["wpm"] = round(stats.word_count / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

        flags = compute_quality_flags(
            mode="q1",
            transcript=transcript,
            stats_obj=stats,
            duration_seconds=dur_s,
        )
        payload.update(flags)

        print_quality_warnings(mode="q1", flags=flags)

        session_id = insert_session(
            topic="focus:q1",
            mode="q1",
            source_text=None,
            transcript=transcript,
            stats_payload=payload,
            audio_path=str(out),
        )

        print(f"\nSession gespeichert: id={session_id} | mode=q1")
        print(f"Transkript:\n{transcript}\n")

    # optional: kleine Hygiene (wie sonst auch)
    cleanup_audio_retention(Path("data/audio"), keep_last=10, keep_days=0)

    print("Fokus-Run beendet.")
    print("TIPP: Fortschritt ansehen mit: python3 sprachapp_main.py report --progress --last 200")

# Focus q2
def cmd_focus_q2(args: argparse.Namespace) -> None:
    """
    Minimaler Fokus-Run: wiederholt q2 N-mal kurz hintereinander.
    - nutzt vorhandene Audio/ASR/Auswertung/Quality-Flags
    - speichert Einträge wie gewohnt
    - greift NICHT in book/news-progress ein
    """
    ensure_db()

    from datetime import datetime, UTC

    rounds = int(args.rounds)
    q_seconds = float(args.q_seconds)
    minutes = max(0.01, q_seconds / 60.0)

    print(f"FOKUS q2: {rounds} Runden á {int(q_seconds)}s")
    print("Aufgabe: Antworte als Q2 (Begründung). 1–2 Sätze, mit weil/denn.\n")
    for i in range(1, rounds + 1):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out = Path("data/audio") / f"{ts}_focus-q2_r{i}.wav"

        print(f"--- Runde {i}/{rounds} ---")
        record_mic_to_wav(out_path=out, minutes=minutes, device=args.device)

        raw = transcribe_with_whisper(str(out))
        transcript = normalize_text(raw)

        stats = compute_stats(transcript)

        dur_s = None
        try:
            dur_s = wav_duration_seconds(out)
        except Exception:
            dur_s = None

        payload = stats.__dict__.copy()
        payload["duration_seconds"] = round(dur_s, 2) if dur_s else None
        payload["wpm"] = round(stats.word_count / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

        flags = compute_quality_flags(
            mode="q2",
            transcript=transcript,
            stats_obj=stats,
            duration_seconds=dur_s,
        )
        payload.update(flags)

        print_quality_warnings(mode="q2", flags=flags)

        session_id = insert_session(
            topic="focus:q2",
            mode="q2",
            source_text=None,
            transcript=transcript,
            stats_payload=payload,
            audio_path=str(out),
        )

        print(f"\nSession gespeichert: id={session_id} | mode=q2")
        print(f"Transkript:\n{transcript}\n")

    # optional: kleine Hygiene (wie sonst auch)
    cleanup_audio_retention(Path("data/audio"), keep_last=10, keep_days=0)

    print("Fokus-Run beendet.")
    print("TIPP: Fortschritt ansehen mit: python3 sprachapp_main.py report --progress --last 200")


# Focus q3
def cmd_focus_q3(args: argparse.Namespace) -> None:
    """
    Minimaler Fokus-Run: wiederholt q3 N-mal kurz hintereinander.
    - nutzt vorhandene Audio/ASR/Auswertung/Quality-Flags
    - speichert Einträge wie gewohnt
    - greift NICHT in book/news-progress ein
    """
    ensure_db()

    from datetime import datetime, UTC

    rounds = int(args.rounds)
    q_seconds = float(args.q_seconds)
    minutes = max(0.01, q_seconds / 60.0)

    print(f"FOKUS q3: {rounds} Runden á {int(q_seconds)}s")
    print("Aufgabe: Antworte als Q3 (Begründung mit Ursache/Wirkung). 1–2 Sätze, mit weil/deshalb.\n")
    for i in range(1, rounds + 1):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out = Path("data/audio") / f"{ts}_focus-q3_r{i}.wav"

        print(f"--- Runde {i}/{rounds} ---")
        record_mic_to_wav(out_path=out, minutes=minutes, device=args.device)

        raw = transcribe_with_whisper(str(out))
        transcript = normalize_text(raw)

        stats = compute_stats(transcript)

        dur_s = None
        try:
            dur_s = wav_duration_seconds(out)
        except Exception:
            dur_s = None

        payload = stats.__dict__.copy()
        payload["duration_seconds"] = round(dur_s, 2) if dur_s else None
        payload["wpm"] = round(stats.word_count / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

        t_low = transcript.lower()
        payload["q3_has_causal"] = ("weil" in t_low) or ("deshalb" in t_low)

        flags = compute_quality_flags(
            mode="q3",
            transcript=transcript,
            stats_obj=stats,
            duration_seconds=dur_s,
        )
        payload.update(flags)

        print_quality_warnings(mode="q3", flags=flags)

        session_id = insert_session(
            topic="focus:q3",
            mode="q3",
            source_text=None,
            transcript=transcript,
            stats_payload=payload,
            audio_path=str(out),
        )

        print(f"\nSession gespeichert: id={session_id} | mode=q3")
        print(f"Transkript:\n{transcript}\n")

    # optional: kleine Hygiene (wie sonst auch)
    cleanup_audio_retention(Path("data/audio"), keep_last=10, keep_days=0)

    print("Fokus-Run beendet.")
    print("TIPP: Fortschritt ansehen mit: python3 sprachapp_main.py report --progress --last 200")


def cmd_focus_retell(args: argparse.Namespace) -> None:
    """
    Minimaler Fokus-Run: wiederholt retell N-mal kurz hintereinander.
    - nutzt vorhandene Audio/ASR/Auswertung/Quality-Flags
    - speichert Einträge wie gewohnt
    - greift NICHT in book/news-progress ein
    """
    ensure_db()

    from datetime import datetime, UTC

    rounds = int(args.rounds)
    minutes = float(args.minutes)

    print(f"FOKUS Wiedergabe: {rounds} Runden á {minutes:.2f} min")
    print("Aufgabe: Kurze Wiedergabe. 2–4 Sätze, ohne Wiederholung.\n")

    for i in range(1, rounds + 1):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out = Path("data/audio") / f"{ts}_focus-retell_r{i}.wav"

        print(f"--- Runde {i}/{rounds} ---")
        record_mic_to_wav(out_path=out, minutes=minutes, device=args.device)

        raw = transcribe_with_whisper(str(out))
        transcript = normalize_text(raw)

        stats = compute_stats(transcript)

        dur_s = None
        try:
            dur_s = wav_duration_seconds(out)
        except Exception:
            dur_s = None

        payload = stats.__dict__.copy()
        payload["duration_seconds"] = round(dur_s, 2) if dur_s else None
        payload["wpm"] = round(stats.word_count / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

        flags = compute_quality_flags(
            mode="retell",
            transcript=transcript,
            stats_obj=stats,
            duration_seconds=dur_s,
        )
        payload.update(flags)

        print_quality_warnings(mode="retell", flags=flags)

        session_id = insert_session(
            topic="focus:retell",
            mode="retell",
            source_text=None,
            transcript=transcript,
            stats_payload=payload,
            audio_path=str(out),
        )

        print(f"\nSession gespeichert: id={session_id} | mode=retell")
        print(f"Transkript:\n{transcript}\n")

    cleanup_audio_retention(Path("data/audio"), keep_last=10, keep_days=0)

    print("Fokus-Run beendet.")
    print("TIPP: Fortschritt ansehen mit: python3 sprachapp_main.py report --progress --last 200")


def cmd_define_vocab_practice(args: argparse.Namespace) -> None:
    ensure_db()

    if args.random:
        vocab = get_vocab_random()
        if not vocab:
            print("Keine Vokabeln vorhanden.")
            return
    else:
        vocab = get_vocab_by_term(args.term)
        if not vocab:
            print(f"Vokabel nicht gefunden: {args.term}")
            return

    term = vocab["term"]
    difficulty = vocab["difficulty"]
    definition = vocab["definition_text"]

    print(f"\nBegriff: {term} [{difficulty}]")
    print(f"Bedeutung: {definition}\n")

    print("Aufgabe:")
    print("- Erkläre das Wort in deinen eigenen Worten.")
    print("- Gib zwei getrennte Beispielsätze.\n")

    transcript = input("Deine Antwort: ").strip()

    backend = get_coach_backend()
    req = CoachRequest(
        topic=term,
        mode="define",
        source_text=definition,
        transcript=transcript,
        stats_payload={"difficulty": difficulty},
    )

    resp = backend.generate(req)
    print_coach_block(resp)
    mark_vocab_practiced(vocab["id"])
    print(f"(progress) practiced={vocab['practice_count'] + 1}")


def cmd_learning_paths_list(args):
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    rows = cur.execute(
        """
        SELECT name, level, description
        FROM learning_path_templates
        WHERE is_active = 1
        ORDER BY level, name
        """
    ).fetchall()

    con.close()

    if not rows:
        print("Keine Lernpfade vorhanden.")
        return

    print("\n--- LERNPFADE ---")
    for r in rows:
        print(f"- {r['name']} [{r['level']}] — {r['description']}")


def cmd_learning_path_show(args):
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    tpl = cur.execute(
        """
        SELECT id, name, level, description
        FROM learning_path_templates
        WHERE name = ?
        """,
        (args.name,),
    ).fetchone()

    if not tpl:
        print(f"Lernpfad nicht gefunden: {args.name}")
        con.close()
        return

    steps = cur.execute(
        """
        SELECT step_order, step_type, config
        FROM learning_path_template_steps
        WHERE template_id = ?
        ORDER BY step_order
        """,
        (tpl["id"],),
    ).fetchall()

    con.close()

    print(f"\nLernpfad: {tpl['name']} [{tpl['level']}]")
    print(tpl["description"])
    if not steps:
        print("Keine Schritte definiert.")
        return

    print("\nSchritte:")
    for s in steps:
        print(f"{s['step_order']}. {s['step_type']} ({s['config']})")


def cmd_sessions_list(args):
    rows = list_sessions_v2(status=None if args.all else "open")
    if not rows:
        print("Keine Sessions vorhanden.")
        return

    print("\n--- SESSIONS ---")
    for r in rows:
        print(
            f"- id={r['id']} template_id={r['template_id']} "
            f"step={r['step_order']} type={r['step_type']} "
            f"status={r['status']} started={r['started_at']} completed={r['completed_at'] or '-'}"
        )


def cmd_sessions_start(args):
    sid = create_session_v2(
        template_id=args.template_id,
        step_order=args.step_order,
        step_type=args.step_type,
        content_ref=args.content_ref,
    )
    print(f"Session gestartet: id={sid}")


def cmd_sessions_complete(args):
    complete_session_v2(args.id)
    print(f"Session completed: id={args.id}")


def cmd_learning_path_start(args):
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    tpl = cur.execute(
        """
        SELECT id, name
        FROM learning_path_templates
        WHERE name = ?
        """,
        (args.name,),
    ).fetchone()

    if not tpl:
        print(f"Lernpfad nicht gefunden: {args.name}")
        con.close()
        return

    # ---- Neuen Run erzeugen ----
    from datetime import datetime, UTC
    now = datetime.now(UTC).isoformat()

    cur.execute(
        """
        INSERT INTO learning_path_runs (template_id, status, started_at, completed_at)
        VALUES (?, 'active', ?, NULL)
        """,
        (tpl["id"], now),
    )
    run_id = cur.lastrowid

    # ---- Alte offene Sessions dieses Templates schließen ----
    cur.execute(
        """
        UPDATE sessions_v2
        SET status = 'completed',
            completed_at = datetime('now')
        WHERE template_id = ?
          AND status = 'open'
        """,
        (tpl["id"],),
    )

    # ---- Schritte laden ----
    steps = cur.execute(
        """
        SELECT step_order, step_type, config
        FROM learning_path_template_steps
        WHERE template_id = ?
        ORDER BY step_order
        """,
        (tpl["id"],),
    ).fetchall()

    if not steps:
        print("Keine Schritte im Lernpfad definiert.")
        con.close()
        return

    print(f"\nStarte Lernpfad: {tpl['name']}")

    first = steps[0]

    # ---- Text ggf. speichern ----
    text_id = None
    if first["step_type"] in ("news", "book"):
        from pathlib import Path
        
        fname = "news.txt" if first["step_type"] == "news" else "book.txt"
        p = Path(fname)

        if not p.exists():
            print(f"Fehlt im Repo-Root: {fname}")
            con.close()
            return

        content = p.read_text(encoding="utf-8").strip()
        if not content:
            print(f"Datei ist leer: {fname}")
            con.close()
            return

        title = f"{first['step_type']} (root file)"

        # WICHTIG: texts mit derselben DB-Verbindung schreiben (sonst "database is locked")
        cur.execute(
            """
            INSERT INTO texts (source_type, title, content, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (first["step_type"], title, content),
        )
        text_id = cur.lastrowid

    # ---- Erste Session anlegen (WICHTIG: gleiche DB-Verbindung verwenden) ----
    from datetime import datetime, UTC
    started_at = datetime.now(UTC).isoformat()

    cur.execute(
        """
        INSERT INTO sessions_v2
            (template_id, step_order, step_type, content_ref, text_id, run_id, status, started_at, completed_at)
        VALUES
            (?, ?, ?, ?, ?, ?, 'open', ?, NULL)
        """,
        (
            int(tpl["id"]),
            int(first["step_order"]),
            first["step_type"],
            first["config"],
            text_id,
            run_id,
            started_at,
        ),
    )
    sid = cur.lastrowid

    con.commit()
    con.close()

    print(f"- Session angelegt: id={sid} step={first['step_order']} type={first['step_type']}")
    print("(linear) Weitere Schritte werden erst nach Abschluss freigeschaltet.")


def cmd_sessions_run(args):
    rows = list_sessions_v2(status="open")
    target = next((r for r in rows if r["id"] == args.id), None)

    if not target:
        print(f"Session nicht gefunden: id={args.id}")
        return

    stype = target["step_type"]
    print(f"\nStarte Session id={args.id} type={stype}")

    # ---- NEWS / BOOK: Text laden -> Auswahl -> Session auto-complete ----
    if stype in ("news", "book"):
        # Local imports, damit du oben nichts anfassen musst
        from sprachapp.core.db import get_con, complete_session_v2

        text_id = target.get("text_id")
        if not text_id:
            print("Kein text_id in dieser Session. (Lernpfad muss beim Start Text speichern.)")
            return

        con = get_con()
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        row = cur.execute(
            "SELECT content FROM texts WHERE id = ?",
            (text_id,),
        ).fetchone()
        con.close()

        if not row:
            print(f"Kein Text gefunden für text_id={text_id}.")
            return

        text = (row["content"] or "").strip()
        if not text:
            print("Text ist leer.")
            return

        print("\n--- TEXT (Preview) ---\n")
        print(text[:1200])
        if len(text) > 1200:
            print("\n...(gekürzt)...")

        print("\n--- RETELL ---")
        input("Erzähle den Inhalt in eigenen Worten (drücke Enter wenn fertig) ")

        # Vorschläge + Auswahl-Loop
        suggestions = generate_vocab_suggestions_stub(text)
        while True:
            chosen = choose_vocab_from_suggestions(suggestions)

            if chosen is None:  # neu
                suggestions = generate_vocab_suggestions_stub(text)
                continue

            if chosen == []:  # quit
                print("Abgebrochen: keine Wörter gespeichert.")
                break

            from sprachapp.core.db import add_vocab, link_session_vocab

            print("Speichere Wörter...")
            for w in chosen:
                vocab_id = add_vocab(
                    term=w,
                    lang="de",
                    difficulty="medium",
                    definition_text="(wird später ergänzt)"
                )
                link_session_vocab(target["id"], vocab_id)
                print(f"- gespeichert & verknüpft: {w}")

            break

        complete_session_v2(target["id"])
        print("Session automatisch abgeschlossen.")
        return

    # ---- DEFINE_VOCAB ----
    if stype == "define_vocab":
        from sprachapp.core.db import get_con, complete_session_v2

        con = get_con()
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Wörter stammen aus der vorherigen Session (step_order - 1) im gleichen Run
        run_id = target.get("run_id")
        if not run_id:
            print("Fehlt run_id in dieser Session. (Lernpfad muss Run-IDs setzen.)")
            con.close()
            return

        prev = cur.execute(
            """
            SELECT id
            FROM sessions_v2
            WHERE run_id = ?
              AND step_order = ?
            """,
            (run_id, int(target["step_order"]) - 1),
        ).fetchone()

        if not prev:
            print("Keine vorherige Session im Run gefunden.")
            con.close()
            return

        prev_session_id = int(prev["id"])

        rows = cur.execute(
            """
            SELECT v.id, v.term
            FROM session_vocab sv
            JOIN vocab v ON sv.vocab_id = v.id
            WHERE sv.session_id = ?
            ORDER BY v.id ASC
            """,
            (prev_session_id,),
        ).fetchall()

        con.close()

        if not rows:
            print("Keine Wörter für diese Define-Session gefunden (vorherige Session hatte keine Auswahl).")
            return

        print("\n--- DEFINE SESSION ---")

        for r in rows:
            print(f"\nWort: {r['term']}")
            input("Erkläre das Wort in eigenen Worten (Enter wenn fertig): ")
            input("Beispielsatz 1 (Enter wenn fertig): ")
            input("Beispielsatz 2 (Enter wenn fertig): ")

        complete_session_v2(target["id"])
        print("Define-Session abgeschlossen.")
        return

    # ---- REVIEW ----
    if stype == "review":
        from sprachapp.core.db import get_con, complete_session_v2
        import random

        con = get_con()
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        run_id = target.get("run_id")
        if not run_id:
            print("Fehlt run_id.")
            con.close()
            return

        # Alle Vokabeln dieses Runs holen
        rows = cur.execute(
            """
            SELECT DISTINCT v.id, v.term
            FROM sessions_v2 s
            JOIN session_vocab sv ON s.id = sv.session_id
            JOIN vocab v ON v.id = sv.vocab_id
            WHERE s.run_id = ?
            """,
            (run_id,),
        ).fetchall()

        con.close()

        if not rows:
            print("Keine Vokabeln für Review gefunden.")
            return

        word = random.choice(rows)

        print("\n--- REVIEW ---")
        print(f"Wort: {word['term']}")
        input("Erkläre das Wort in eigenen Worten (Enter wenn fertig): ")
        input("Beispielsatz 1 (Enter wenn fertig): ")
        input("Beispielsatz 2 (Enter wenn fertig): ")

        complete_session_v2(target["id"])
        print("Review-Session abgeschlossen.")
        return

    print("Unbekannter step_type")


def generate_vocab_suggestions_stub(text: str) -> list[str]:
    """
    Stub: simuliert KI-Wortvorschläge aus einem Text.
    Später wird hier der echte OpenAI-Call eingebaut.
    """
    # Dummy-Vorschläge (nur für Strukturtest)
    return ["Beispielwort1", "Beispielwort2", "Beispielwort3"]


def choose_vocab_from_suggestions(suggestions: list[str]) -> list[str] | None:
    """
    Gibt eine Liste ausgewählter Wörter zurück.
    - 'neu' => None (Caller soll neu generieren)
    - 'quit' => [] (Abbruch ohne Auswahl)
    - '1,3' => ausgewählte Wörter
    """
    while True:
        print("\nVorschläge:")
        for i, w in enumerate(suggestions, start=1):
            print(f"{i}) {w}")

        raw = input("\nWähle (z.B. 1,3) | 'neu' | 'quit': ").strip().lower()

        if raw == "neu":
            return None
        if raw == "quit":
            return []

        # Zahlenliste parsen
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            print("Bitte eine Auswahl eingeben (z.B. 1,3) oder 'neu'/'quit'.")
            continue

        idxs: list[int] = []
        ok = True
        for p in parts:
            if not p.isdigit():
                ok = False
                break
            idxs.append(int(p))

        if not ok:
            print("Ungültig. Nutze z.B. 1,3 oder 'neu' oder 'quit'.")
            continue

        chosen: list[str] = []
        for i in idxs:
            if i < 1 or i > len(suggestions):
                print(f"Index außerhalb der Liste: {i}")
                ok = False
                break
            chosen.append(suggestions[i - 1])

        if not ok:
            continue

        # Duplikate entfernen, Reihenfolge behalten
        seen = set()
        uniq = []
        for w in chosen:
            if w not in seen:
                seen.add(w)
                uniq.append(w)

        return uniq


def cmd_debug_vocab_suggest(args):
    text = "Dummy-Text für Vorschläge."
    suggestions = generate_vocab_suggestions_stub(text)

    while True:
        chosen = choose_vocab_from_suggestions(suggestions)

        if chosen is None:
            print("(debug) neu generieren…")
            suggestions = generate_vocab_suggestions_stub(text)
            continue

        if chosen == []:
            print("(debug) quit")
            return

        print("(debug) gewählt:", ", ".join(chosen))
        return


def cmd_learning_path_next(args):
    con = get_con()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    tpl = cur.execute(
        "SELECT id, name FROM learning_path_templates WHERE name = ?",
        (args.name,),
    ).fetchone()

    if not tpl:
        print(f"Lernpfad nicht gefunden: {args.name}")
        con.close()
        return

    # Letzten aktiven Run holen
    run = cur.execute(
        """
        SELECT id
        FROM learning_path_runs
        WHERE template_id = ?
          AND status = 'active'
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (tpl["id"],),
    ).fetchone()

    if not run:
        print("Kein aktiver Run gefunden. Starte zuerst: learning-paths start --name ...")
        con.close()
        return

    run_id = int(run["id"])

    # Schritte des Templates
    steps = cur.execute(
        """
        SELECT step_order, step_type, config
        FROM learning_path_template_steps
        WHERE template_id = ?
        ORDER BY step_order
        """,
        (tpl["id"],),
    ).fetchall()

    if not steps:
        print("Keine Schritte im Lernpfad definiert.")
        con.close()
        return

    # Höchsten completed step_order NUR in diesem Run
    row = cur.execute(
        """
        SELECT MAX(step_order)
        FROM sessions_v2
        WHERE run_id = ?
          AND status = 'completed'
        """,
        (run_id,),
    ).fetchone()

    max_completed = row[0] if row and row[0] is not None else 0
    next_order = max_completed + 1

    next_step = next((s for s in steps if int(s["step_order"]) == int(next_order)), None)
    if not next_step:
        # Run als completed markieren
        cur.execute(
            """
            UPDATE learning_path_runs
            SET status='completed',
                completed_at=datetime('now')
            WHERE id = ?
            """,
            (run_id,),
        )
        con.commit()
        con.close()
        print("Lernpfad ist fertig. Run wurde abgeschlossen.")
        return

    # Optional: verhindern, dass mehrere open Sessions im selben Run existieren
    open_row = cur.execute(
        "SELECT id FROM sessions_v2 WHERE run_id = ? AND status = 'open' LIMIT 1",
        (run_id,),
    ).fetchone()
    if open_row:
        con.close()
        print(f"Es gibt bereits eine offene Session (id={open_row[0]}). Bitte erst ausführen/abschließen.")
        return

    con.close()

    # Für dein Template ist step 2/3 nicht news/book, daher text_id=None.
    sid = create_session_v2(
        template_id=tpl["id"],
        run_id=run_id,
        step_order=int(next_step["step_order"]),
        step_type=next_step["step_type"],
        content_ref=next_step["config"],
        text_id=None,
    )

    print(f"Nächste Session angelegt: id={sid} run_id={run_id} step={next_step['step_order']} type={next_step['step_type']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sprachapp")
    sub = p.add_subparsers(dest="cmd", required=True)

    # speak
    s = sub.add_parser("speak", help="Aufnehmen/Transkribieren/Auswertung (lesen|Wiedergabe)")
    s.add_argument("--list-devices", action="store_true", help="Zeigt verfügbare Input-Geräte an.")
    s.add_argument("--audio", default=None, help="Pfad zur Audio-Datei (wav/mp3/m4a).")
    s.add_argument("--record", action="store_true", help="Nimmt Audio vom Mikrofon auf und speichert es als WAV.")
    s.add_argument("--minutes", type=float, default=0.5, help="Maximale Aufnahmezeit in Minuten.")
    s.add_argument("--device", type=int, default=None, help="Input-Device-ID (optional).")
    s.add_argument("--topic", default=None, help="Topic/Label")
    s.add_argument("--mode", choices=["read", "retell"], default="retell")
    s.add_argument("--source-text", default=None, help="Prompt-Text direkt (optional)")
    s.add_argument("--prompt-file", default=None, help="TXT-Datei mit Prompt-Text (optional)")
    s.add_argument("--cut-punkt", action="store_true", help="Schneidet Transkript bis letztes 'punkt'.")
    s.add_argument("--delete-audio", action="store_true", help="Löscht WAV nach Speicherung.")
    s.add_argument("--keep-last-audios", type=int, default=0, help="Behält nur die letzten N WAVs.")
    s.add_argument("--keep-days", type=int, default=0, help="Löscht WAVs älter als X Tage.")
    s.add_argument("--suggest-k", type=int, default=8, help="Anzahl Zielbegriffe.")

    # book
    b = sub.add_parser("book", help="Buch/TXT Tutor (Chunk -> Wiedergabe -> Fragen)")
    b.add_argument("--book-file", required=True, help="TXT-Datei (Buch/Kapitel).")
    b.add_argument("--words-per-chunk", type=int, default=220, help="Wörter pro Abschnitt.")
    b.add_argument("--chunk", type=int, default=None, help="Expliziter Chunk-Index (0-basiert).")
    b.add_argument("--next", action="store_true", help="Zum nächsten Chunk.")
    b.add_argument("--repeat", action="store_true", help="Aktuellen Chunk wiederholen.")
    b.add_argument("--read-first", action="store_true", help="Erst vorlesen (Aufwärmen), dann Wiedergabe.")
    b.add_argument("--questions", type=int, default=3, help="Anzahl Standardfragen (1-3).")
    b.add_argument("--q-seconds", type=int, default=15,help="Aufnahmezeit pro Frage in Sekunden (kurz halten).")
    b.add_argument("--retell-seconds", type=int, default=30, help="Aufnahmezeit für Wiedergabe in Sekunden.")
    b.add_argument("--prep", choices=["enter", "timed", "none"], default="enter",
                   help="Vorbereitung vor Wiedergabe: enter=unbegrenzt, timed=mit --prep-seconds, none=sofort.")
    b.add_argument("--prep-seconds", type=int, default=90,
                   help="Nur relevant bei --prep timed.")
    b.add_argument("--device", type=int, default=None, help="Input-Device-ID (optional).")
    b.add_argument("--minutes", type=float, default=0.5, help="Maximale Aufnahmezeit für lesen/Wiedergabe.")
    b.add_argument("--cut-punkt", action="store_true", help="Schneidet Transkript bis letztes 'punkt'.")
    b.add_argument("--keep-last-audios", type=int, default=10, help="Behält nur die letzten N WAVs.")
    b.add_argument("--level", choices=["easy", "medium", "hard"], default="easy", help="Schwierigkeitsstufe: easy (kurz), medium (ausführlicher), hard (strukturiert).")

    # stats / report (Report)
    stats_p = sub.add_parser("stats", help="Zeigt die letzten Einträge (Tabelle) und optional CSV-Export.")
    report_p = sub.add_parser("report", help="Alias für 'stats' (zeigt die letzten Einträge und optional CSV-Export).")

    for r in (stats_p, report_p):
        r.add_argument("--last", type=int, default=20, help="Anzahl letzter Einträge.")
        r.add_argument("--mode", default=None, help="Filter: Wiedergabe, q1, q2, q3, lesen ...")
        r.add_argument("--csv", default=None, help="Optional: CSV-Datei schreiben, z.B. out.csv")
        r.add_argument("--summary", action="store_true", help="Zeigt Durchschnittswerte (Trend) statt Tabelle.")
        r.add_argument("--progress", action="store_true", help="Fortschritt je Modus (Median: wc/wpm/uniq, Quoten: lowq/empty).")
        r.add_argument("--only-lowq", action="store_true", help="Zeigt nur Einträge mit low_quality=True.")
        r.add_argument("--only-empty", action="store_true", help="Zeigt nur Einträge mit asr_empty=True.")    
    
    # focus (minimal: q1/q2/q3/retell)
    f = sub.add_parser("focus", help="Fokus-Run: gezieltes Üben eines Modus (q1/q2/q3/Wiedergabe).")
    f.add_argument("mode", choices=["q1", "q2", "q3", "retell"], help="Fokus-Modus (q1=These, q2=Begründung, q3=Ursache/Wirkung, Wiedergabe=Zusammenfassung).")
    f.add_argument("--rounds", type=int, default=3, help="Anzahl Wiederholungen.")
    f.add_argument("--q-seconds", type=int, default=15, help="Für q1/q2/q3: Aufnahmezeit pro Runde in Sekunden.")
    f.add_argument("--minutes", type=float, default=0.5, help="Nur für Wiedergabe: Aufnahmezeit pro Runde in Minuten (z. B. 0.5 = 30s).")
    f.add_argument("--device", type=int, default=None, help="Input-Device-ID (optional).")
   
    # news
    n = sub.add_parser("news", help="News/TXT Tutor (Chunk -> Wiedergabe -> Fragen)")
    n.add_argument("--news-file", required=True, help="TXT-Datei mit News/Inhalt.")
    n.add_argument("--words-per-chunk", type=int, default=220, help="Wörter pro Abschnitt.")
    n.add_argument("--chunk", type=int, default=None, help="Expliziter Chunk-Index (0-basiert).")
    n.add_argument("--next", action="store_true", help="Zum nächsten Chunk.")
    n.add_argument("--repeat", action="store_true", help="Aktuellen Chunk wiederholen.")
    n.add_argument("--device", type=int, default=None, help="Input-Device-ID (optional).")
    n.add_argument("--minutes", type=float, default=0.5, help="Maximale Aufnahmezeit für Wiedergabe.")
    n.add_argument("--questions", type=int, default=3, help="Anzahl Fragen (1-3).")
    n.add_argument("--q-seconds", type=int, default=15, help="Aufnahmezeit pro Frage in Sekunden.")
    n.add_argument("--retell-seconds", type=int, default=30, help="Aufnahmezeit für Wiedergabe in Sekunden.")
    n.add_argument("--prep", choices=["enter", "timed", "none"], default="enter",
                   help="Vorbereitung vor Wiedergabe: enter=unbegrenzt, timed=mit --prep-seconds, none=sofort.")
    n.add_argument("--prep-seconds", type=int, default=90, help="Nur relevant bei --prep timed.")
    n.add_argument("--cut-punkt", action="store_true", help="Schneidet Transkript bis letztes 'punkt'.")
    n.add_argument("--keep-last-audios", type=int, default=10, help="Behält nur die letzten N WAVs.")
    n.add_argument("--keep-days", type=int, default=0, help="Löscht WAVs älter als X Tage (0=aus).")
    n.add_argument("--level", choices=["easy", "medium", "hard"], default="easy", help="Schwierigkeitsstufe: easy (kurz), medium (ausführlicher), hard (strukturiert).")

    # define "wiki"
    d = sub.add_parser("define", help="Begriff erklären (Text) und dann Wiedergabe/Q1–Q3 üben.")
    d.add_argument("--term", required=True, help="Begriff, z.B. 'Endoskop'.")
    d.add_argument("--text", default=None, help="Erklärungstext (kurz). Wenn leer, nutze --auto.")
    d.add_argument("--auto", action="store_true", help="Erklärungstext aus data/define_terms.json laden.")
    d.add_argument("--level", choices=["easy", "medium", "hard"], default="easy", help="Schwierigkeitsstufe.")
    d.add_argument("--retell-seconds", type=int, default=30, help="Aufnahmezeit für Wiedergabe in Sekunden.")
    d.add_argument("--q-seconds", type=int, default=15, help="Aufnahmezeit pro Frage in Sekunden.")
    d.add_argument("--questions", type=int, default=3, help="Anzahl Fragen (1-3).")
    d.add_argument("--prep", choices=["enter", "timed", "none"], default="enter",
                   help="Vorbereitung vor Wiedergabe: enter=unbegrenzt, timed=mit --prep-seconds, none=sofort.")
    d.add_argument("--prep-seconds", type=int, default=90, help="Nur relevant bei --prep timed.")
    d.add_argument("--device", type=int, default=None, help="Input-Device-ID (optional).")
    d.add_argument("--cut-punkt", action="store_true", help="Schneidet Transkript bis letztes 'punkt'.")
    d.add_argument("--keep-last-audios", type=int, default=10, help="Behält nur die letzten N WAVs.")
    d.add_argument("--keep-days", type=int, default=0, help="Löscht WAVs älter als X Tage (0=aus).")

    # selfcheck
    c = sub.add_parser("selfcheck", help="Technischer Systemcheck (Imports/DB/Filesystem/Report).")
    c.add_argument("--verbose", action="store_true", help="Mehr Details bei Fehlern.")
    c.add_argument("--load-model", action="store_true", help="Lädt Whisper base Modell (kann dauern).")
    c.add_argument("--list-devices", action="store_true", help="Listet Input-Geräte (sounddevice) auf.")
    c.add_argument("--smoke-asr", action="store_true", help="Erzeugt Test-WAV und führt transcribe_with_whisper aus.")
    
    # define-vocab (neu, MVP7/A2-2)
    dv = sub.add_parser("define-vocab", help="Vokabel-Trainer (DB): add/list (ohne Coach, ohne Hints).")
    dv_sub = dv.add_subparsers(dest="dv_cmd", required=True)

    dv_add = dv_sub.add_parser("add", help="Vokabel speichern/aktualisieren.")
    dv_add.add_argument("--term", required=True, help="Begriff, z. B. 'Axt'.")
    dv_add.add_argument("--definition", required=True, help="Bedeutungstext (kurz).")
    dv_add.add_argument("--level", choices=["easy", "medium", "hard"], default="medium", help="Schwierigkeitsstufe.")
    dv_add.add_argument("--lang", default="de", help="Sprache, default: de")
    dv_add.add_argument("--example1", default=None, help="Beispielsatz 1 (optional).")
    dv_add.add_argument("--example2", default=None, help="Beispielsatz 2 (optional).")
    dv_add.add_argument("--source", default="manual", help="Quelle: manual|news|book (optional).")

    dv_list = dv_sub.add_parser("list", help="Alphabetische Liste aller Vokabeln.")
    dv_practice = dv_sub.add_parser("practice", help="Vokabel üben (Coach + Hints on-the-fly).")
    dv_practice.add_argument("--term", help="Begriff gezielt üben.")
    dv_practice.add_argument("--random", action="store_true", help="Zufällige Vokabel üben.")
    
    lp = sub.add_parser("learning-paths", help="Lernpfade anzeigen (Templates).")
    lp.set_defaults(func=cmd_learning_paths_list)
    lp_show = lp.add_subparsers(dest="lp_cmd")

    lp_show_cmd = lp_show.add_parser("show", help="Lernpfad anzeigen")
    lp_show_cmd.add_argument("--name", required=True, help="Name des Lernpfads")
    lp_show_cmd.set_defaults(func=cmd_learning_path_show)
    
    lp_start = lp_show.add_parser("start", help="Lernpfad starten")
    lp_start.add_argument("--name", required=True, help="Name des Lernpfads")
    lp_start.set_defaults(func=cmd_learning_path_start)

    lp_next = lp_show.add_parser("next", help="Nächsten Schritt als Session anlegen (linear, manuell)")
    lp_next.add_argument("--name", required=True, help="Name des Lernpfads")
    lp_next.set_defaults(func=cmd_learning_path_next)

    s = sub.add_parser("sessions", help="Sessions v2 (Stub): start/list")
    s_sub = s.add_subparsers(dest="s_cmd", required=True)

    s_list = s_sub.add_parser("list", help="Sessions anzeigen")
    s_list.add_argument("--all", action="store_true", help="auch completed anzeigen")

    s_start = s_sub.add_parser("start", help="Session starten (Stub)")
    s_start.add_argument("--template-id", type=int, required=True)
    s_start.add_argument("--step-order", type=int, required=True)
    s_start.add_argument("--step-type", required=True, choices=["news", "define_vocab", "review"])
    s_start.add_argument("--content-ref", default=None)
    
    s_complete = s_sub.add_parser("complete", help="Session abschließen")
    s_complete.add_argument("--id", type=int, required=True)

    s_run = s_sub.add_parser("run", help="Session ausführen (Stub)")
    s_run.add_argument("--id", type=int, required=True)

    dbg = sub.add_parser("debug-vocab-suggest", help="Debug: Vokabelvorschläge auswählen (Stub).")
    dbg.set_defaults(func=cmd_debug_vocab_suggest)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    ensure_db()
    if hasattr(args, "func"):
        args.func(args)
        return

    if args.cmd == "learning-paths":
        args.func(args)
        return

    if args.cmd == "learning-paths" and hasattr(args, "func"):
        args.func(args)
        return

    if args.cmd == "speak":
        if args.list_devices:
            list_input_devices()
            return
        cmd_speak(args)
        return

    if args.cmd == "focus":
        if args.mode == "q1":
            cmd_focus_q1(args)
            return
        if args.mode == "q2":
            cmd_focus_q2(args)
            return
        if args.mode == "q3":
            cmd_focus_q3(args)
            return
        if args.mode == "retell":
            cmd_focus_retell(args)
            return
        raise SystemExit(f"Nicht unterstützter Fokus-Modus: {args.mode}")

    if args.cmd in ("stats", "report"):
        rows = fetch_last_sessions(last=args.last, mode=args.mode)

        if getattr(args, "only_lowq", False):
            rows = [x for x in rows if x.low_quality is True]

        if getattr(args, "only_empty", False):
            rows = [x for x in rows if x.asr_empty is True]

        if not rows:
            # CSV soll auch bei 0 Zeilen erzeugt werden (mindestens Header).
            if args.csv:
                write_csv(rows, args.csv)

            print("Keine Einträge gefunden.")
            print("Tipp: Erzeuge zuerst Einträge mit 'news' oder 'book', dann:")
            print("  python3 sprachapp_main.py report --last 20")
            return

        if args.progress:
            print_progress(rows)
        elif args.summary:
            print_summary(rows)
        else:
            print_table(rows)

        if args.csv:
            write_csv(rows, args.csv)
        return

    if args.cmd == "book":
        run_book_session(
            book_file=Path(args.book_file),
            words_per_chunk=args.words_per_chunk,
            chunk=args.chunk,
            next_=args.next,
            repeat=args.repeat,
            device=args.device,
            minutes=args.minutes,
            keep_last_audios=args.keep_last_audios,
            cut_punkt=args.cut_punkt,
            read_first=args.read_first,
            questions=args.questions,
            prep=args.prep,
            prep_seconds=args.prep_seconds,
            q_seconds=args.q_seconds,
            level=args.level,
            retell_seconds=args.retell_seconds,
        )
        return
    
    if args.cmd == "news":
        ensure_db()
        run_news_session(
            news_file=Path(args.news_file),
            words_per_chunk=args.words_per_chunk,
            chunk=args.chunk,
            next_=args.next,
            repeat=args.repeat,
            device=args.device,
            minutes=args.minutes,
            q_seconds=args.q_seconds,
            keep_last_audios=args.keep_last_audios,
            cut_punkt=args.cut_punkt,
            questions=args.questions,
            prep=args.prep,
            prep_seconds=args.prep_seconds,
            level=args.level,
            retell_seconds=args.retell_seconds,
        )
        return

    if args.cmd == "define":
        run_define_session(
            term=args.term,
            text=args.text,
            auto=args.auto,
            level=args.level,
            device=args.device,
            retell_seconds=args.retell_seconds,
            q_seconds=args.q_seconds,
            questions=args.questions,
            prep=args.prep,
            prep_seconds=args.prep_seconds,
            cut_punkt=args.cut_punkt,
            keep_last_audios=args.keep_last_audios,
            keep_days=args.keep_days,
        )
        return

    if args.cmd == "define-vocab":
        if args.dv_cmd == "add":
            cmd_define_vocab_add(args)
            return
        if args.dv_cmd == "list":
            cmd_define_vocab_list(args)
            return
        if args.dv_cmd == "practice":
            cmd_define_vocab_practice(args)
            return
        raise SystemExit(f"Unbekannter define-vocab Befehl: {args.dv_cmd}")

    if args.cmd == "selfcheck":
        raise SystemExit(run_selfcheck(
            verbose=args.verbose,
            load_model=args.load_model,
            list_devices=args.list_devices,
            smoke_asr=args.smoke_asr,
        ))

    if args.cmd == "sessions":
        if args.s_cmd == "list":
            cmd_sessions_list(args)
            return
        if args.s_cmd == "start":
            cmd_sessions_start(args)
            return
        if args.s_cmd == "complete":
            cmd_sessions_complete(args)
            return
        if args.s_cmd == "run":
            cmd_sessions_run(args)
            return

if __name__ == "__main__":
    main()


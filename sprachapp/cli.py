from __future__ import annotations

import argparse
from pathlib import Path

from sprachapp.core.db import (
    ensure_db,
    insert_session,
    add_vocab,
    list_vocab_alpha,
    get_vocab_by_term,
    get_vocab_random,
    mark_vocab_practiced,
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
        print(f"- {term} [{level}] — {definition}")


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

    # selfcheck
    c = sub.add_parser("selfcheck", help="Technischer Systemcheck (Imports/DB/Filesystem/Report).")
    c.add_argument("--verbose", action="store_true", help="Mehr Details bei Fehlern.")
    c.add_argument("--load-model", action="store_true", help="Lädt Whisper base Modell (kann dauern).")
    c.add_argument("--list-devices", action="store_true", help="Listet Input-Geräte (sounddevice) auf.")
    c.add_argument("--smoke-asr", action="store_true", help="Erzeugt Test-WAV und führt transcribe_with_whisper aus.")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    ensure_db()
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

if __name__ == "__main__":
    main()
from __future__ import annotations

from pathlib import Path
import re

from sprachapp.core.db import ensure_db
from sprachapp.core.text import normalize_text, cut_at_punkt
from sprachapp.core.audio import record_mic_to_wav, wav_duration_seconds, cleanup_audio_retention
from sprachapp.core.asr import transcribe_with_whisper
from sprachapp.core.stats import compute_stats
from sprachapp.modules._tutor_common import compute_quality_flags, print_quality_warnings
from sprachapp.core.db import insert_session
from sprachapp.core.coach import generate_coach_feedback, CoachInput


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9äöüß]+", "-", s, flags=re.IGNORECASE)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "term"


def _prompt_retell(level: str) -> str:
    if level == "hard":
        return "Wiedergabe (schwer): 4–6 Sätze. Struktur: Thema → 3 Punkte → Schluss/Fazit."
    if level == "medium":
        return "Wiedergabe (mittel): 3–5 Sätze. 2 Details + 1 Beispiel."
    return "Wiedergabe (leicht): 2–3 Sätze. Erkläre es einfach."


def _prompt_q(level: str, q: int) -> str:
    # minimal, konsistent mit eurem System
    if q == 1:
        return "Frage 1 (These): Formuliere die Kernaussage in genau 1 Satz."
    if q == 2:
        return "Frage 2 (Gründe): Nenne 2 Gründe und ein kurzes Beispiel."
    return "Frage 3 (Ursache→Wirkung): Erkläre Ursache → Wirkung → Folge (2–3 Sätze)."


def run_define_session(
    term: str,
    text: str | None,
    auto: bool = False,
    level: str = "easy",
    device: int | None = None,
    retell_seconds: int = 60,
    q_seconds: int = 25,
    questions: int = 3,
    prep: str = "enter",
    prep_seconds: int = 90,
    cut_punkt: bool = False,
    keep_last_audios: int = 10,
    keep_days: int = 0,
) -> None:
    ensure_db()

    # Text-Quelle: direkt (--text) oder lokal (--auto)
    term_key = term.strip().lower()

    if auto:
        import json
        p = Path("data") / "define_terms.json"
        if not p.exists():
            raise SystemExit("define --auto: data/define_terms.json fehlt.")
        data = json.loads(p.read_text(encoding="utf-8"))
        loaded = data.get(term_key)
        if not loaded:
            raise SystemExit(f"define --auto: Begriff nicht gefunden: {term_key}")
        text = loaded

    if text is None:
        raise SystemExit("define: Bitte --text angeben oder --auto nutzen.")

    clean_text = text.strip()
    if not clean_text or clean_text in {"...", "…"}:
        raise SystemExit("define: --text ist leer/Platzhalter. Bitte echten Erklärungstext angeben.")

    source_text = f"{term}\n\n{clean_text}".strip()

    # Audio-Device bewusst machen (define ist sensibel für Stille)
    if device is None:
        from sprachapp.core.audio import list_input_devices

        print("\nHINWEIS: Kein Audio-Device angegeben.")
        print("Verfügbare Input-Geräte:")
        list_input_devices()
        print("\nEmpfehlung: define immer mit --device <ID> starten.")

        ans = input("Trotzdem mit Standard-Device fortfahren? [y/N]: ").strip().lower()
        if ans != "y":
            raise SystemExit("Abgebrochen. Starte erneut mit --device <ID>.")

    Path("data/audio").mkdir(parents=True, exist_ok=True)

    topic_base = f"define:{_slug(term)}"
    source_text = f"{term}\n\n{text.strip()}".strip()

    # Schutz gegen Platzhalter/leer (sonst übst du gegen Nonsens)
    clean_text = text.strip()
    if not clean_text or clean_text in {"...", "…"}:
        raise SystemExit("define: --text ist leer/Platzhalter. Bitte echten Erklärungstext angeben.")

    source_text = f"{term}\n\n{clean_text}".strip()
    
    # Prep (Text anzeigen → dann genau 1 Start-Aktion)
    print(f"\nBEGRIFF: {term}\n")
    print(source_text)
    print("\n---")

    if prep == "enter":
        # genau 1x Enter = Start
        input("Drücke Enter, um mit Wiedergabe zu starten… ")

    elif prep == "timed":
        import time
        print(f"Vorbereitung: {prep_seconds}s… (Ctrl+C zum Abbrechen)")
        try:
            time.sleep(int(prep_seconds))
        except KeyboardInterrupt:
            print("\nAbgebrochen.")
            raise SystemExit(0)
        # nach Countdown: genau 1x Enter = Start
        input("Drücke Enter, um mit Wiedergabe zu starten… ")

    elif prep == "none":
        # sofort (bewusst)
        pass

    # RETELL
    from datetime import datetime, UTC
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    out = Path("data/audio") / f"{ts}_define-retell.wav"

    print("\n" + _prompt_retell(level) + "\n→ Vermeide gleiche Formulierungen wie zuvor.")
    try:
        record_mic_to_wav(out_path=out, minutes=max(1/60, retell_seconds / 60.0), device=device)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        raise SystemExit(0)

    raw = transcribe_with_whisper(str(out))
    transcript = cut_at_punkt(raw) if cut_punkt else normalize_text(raw)

    dur_s = None
    try:
        dur_s = wav_duration_seconds(out)
    except Exception:
        dur_s = None

    stats = compute_stats(transcript)
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
        topic=f"{topic_base}:retell",
        mode="retell",
        source_text=source_text,
        transcript=transcript,
        stats_payload=payload,
        audio_path=str(out),
    )
    print(f"\nSession gespeichert: id={session_id} | mode=retell")
    print("TIPP: Fortschritt ansehen mit: python3 sprachapp_main.py report --progress --last 200")
    print("\nTranskript:")
    print(transcript + "\n")

    #COACH
    
    coach_out = generate_coach_feedback(
        CoachInput(
            mode="retell",
            topic=f"define:{term_key}",
            source_text=source_text,
            transcript=transcript,
            stats_payload=payload,
        )
    )

    print("COACH:")
    print(coach_out.feedback_text + "\n")


    # Q1–Qn
    for i in range(1, int(questions) + 1):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out = Path("data/audio") / f"{ts}_define-q{i}.wav"

        q_text = _prompt_q(level, i)
        print("\n" + "-" * 80)
        print(q_text)
        print("→ Beginne nicht mit demselben Wort wie zuvor.")
        print("-" * 80)

        try:
            record_mic_to_wav(out_path=out, minutes=max(1/60, q_seconds / 60.0), device=device)
        except KeyboardInterrupt:
            print("\nAbgebrochen.")
            raise SystemExit(0)

        raw = transcribe_with_whisper(str(out))
        transcript = cut_at_punkt(raw) if cut_punkt else normalize_text(raw)

        dur_s = None
        try:
            dur_s = wav_duration_seconds(out)
        except Exception:
            dur_s = None

        stats = compute_stats(transcript)
        payload = stats.__dict__.copy()
        payload["duration_seconds"] = round(dur_s, 2) if dur_s else None
        payload["wpm"] = round(stats.word_count / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

        mode = f"q{i}"
        flags = compute_quality_flags(
            mode=mode,
            transcript=transcript,
            stats_obj=stats,
            duration_seconds=dur_s,
        )
        payload.update(flags)
        print_quality_warnings(mode=mode, flags=flags)

        session_id = insert_session(
            topic=f"{topic_base}:{mode}",
            mode=mode,
            source_text=source_text,
            transcript=transcript,
            stats_payload=payload,
            audio_path=str(out),
        )
        print(f"\nSession gespeichert: id={session_id} | mode={mode}")
        print("TIPP: Fortschritt ansehen mit: python3 sprachapp_main.py report --progress --last 200")
        print("\nTranskript:")
        print(transcript + "\n")

        coach_out = generate_coach_feedback(
            CoachInput(
                mode=mode,                     # hier EXISTIERT mode
                topic=f"define:{term_key}",
                source_text=source_text,
                transcript=transcript,
                stats_payload=payload,
            )
        )

        print("COACH:")
        print(coach_out.feedback_text + "\n")

    cleanup_audio_retention(Path("data/audio"), keep_last=keep_last_audios, keep_days=keep_days)
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from sprachapp.core.audio import record_mic_to_wav, wav_duration_seconds, cleanup_audio_retention
from sprachapp.core.asr import transcribe_with_whisper
from sprachapp.core.text import normalize_text, cut_at_punkt
from sprachapp.core.stats import compute_stats, suggest_target_terms, suggest_bonus_terms, terms_used
from sprachapp.core.db import insert_session
from sprachapp.core.feedback import make_q3_feedback

from sprachapp.modules._tutor_common import compute_quality_flags, print_quality_warnings, stats_to_payload

from sprachapp.core.coach_backend_factory import get_coach_backend
from sprachapp.core.coach_backend import CoachRequest

from sprachapp.core.coach_print import print_coach_block

PROGRESS_PATH = Path("data/book_progress.json")



def _book_key(book_file: Path) -> str:
    h = hashlib.sha1(str(book_file.resolve()).encode("utf-8")).hexdigest()[:12]
    return h


def load_book_text(book_file: Path) -> str:
    return book_file.read_text(encoding="utf-8").strip()


def chunk_words(text: str, words_per_chunk: int = 220) -> list[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), words_per_chunk):
        chunks.append(" ".join(words[i:i + words_per_chunk]))
    return chunks


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_progress(prog: dict):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


def get_chunk_index(book_file: Path, total_chunks: int, chunk: int | None, next_: bool, repeat: bool) -> int:
    prog = load_progress()
    key = _book_key(book_file)
    idx = int(prog.get(key, 0))

    if chunk is not None:
        idx = chunk
    elif next_:
        idx = idx + 1
    elif repeat:
        idx = idx
    else:
        idx = idx

    if idx < 0:
        idx = 0
    if idx >= total_chunks:
        idx = total_chunks - 1

    prog[key] = idx
    save_progress(prog)
    return idx


def _prompt_for(level: str, mode: str) -> str:
    level = (level or "easy").strip().lower()
    mode = (mode or "").strip().lower()

    if mode == "q1":
        if level == "easy":
            return "Q1 (leicht): Genau 1 Satz. Kernaussage/These. Kein Beispiel, keine Wiederholung aus der Wiedergabe. Nicht mit „Ein … ist …“ beginnen."
        if level == "medium":
            return "Q1 (mittel): Genau 1 Satz. These + kurze Begründung im selben Satz (1× weil/denn). Kein Beispiel. Nicht mit „Ein … ist …“ beginnen."
        return "Q1 (schwer): Genau 1 Satz. Präzise These mit klarer Wertung (ohne Aufzählung, ohne Beispiel). Nicht mit „Ein … ist …“ beginnen."

    if mode == "q2":
        if level == "easy":
            return "Q2 (leicht): Genau 2 Sätze: 2 Gründe (je 1 Satz). Keine Wiederholung aus Q1. Kein Beispiel. Nicht mit „Ein … ist …“ beginnen."
        if level == "medium":
            return "Q2 (mittel): Genau 3 Sätze: 2 Gründe + genau 1 Beispiel (Beispiel als eigener Satz). Keine Wiederholung aus Q1/Q2. Nicht mit „Ein … ist …“ beginnen."
        return "Q2 (schwer): Genau 3 Sätze: 2 starke Gründe + 1 konkretes Beispiel. Keine Floskeln, keine Aufzählungswörter („erstens…“)."

    if mode == "q3":
        if level == "easy":
            return "Q3 (leicht): Genau 3 Sätze: Ursache → Wirkung → Folge (je 1 Satz). Kein Beispiel. Nicht mit „Ein … ist …“ beginnen."
        if level == "medium":
            return "Q3 (mittel): Genau 3 Sätze: Ursache → Wirkung → Folge. Nutze genau 1× weil/deshalb/daher (nur einmal)."
        return "Q3 (schwer): Genau 3 Sätze: Ursache → Wirkung → Folge. Sehr präzise, keine Wiederholung aus Q1/Q2."

    # Fallback
    return "Antwort: bitte kurz und klar."


def ask_questions_default(n: int = 3, level: str = "easy") -> list[str]:
    modes = ["q1", "q2", "q3"]
    prompts = [_prompt_for(level, m) for m in modes]
    return prompts[:max(1, min(n, len(prompts)))]


def _with_retell_hint(text: str) -> str:
    return text + "\n→ Vermeide gleiche Formulierungen wie zuvor."


def _with_variation_hint(text: str) -> str:
    return text + "\n→ Beginne nicht mit demselben Wort wie zuvor."


def _prep_phase(prep: str, prep_seconds: int):
    if prep == "enter":
        try:
            input("\nVORBEREITUNG: Lies/denk in Ruhe. Drücke Enter, wenn du bereit bist für Wiedergabe...")
        except KeyboardInterrupt:
            print("\nAbgebrochen.")
            raise SystemExit(0)            
    elif prep == "timed":
        import time
        print(f"\nVORBEREITUNG: {prep_seconds}s Lesen/Denken (keine Aufnahme).")
        for r in range(prep_seconds, 0, -1):
            print(f"  noch {r:>3}s...", end="\r", flush=True)
            time.sleep(1)
        print("\nVorbereitung beendet.")
    elif prep == "none":
        print("\nVORBEREITUNG übersprungen (sofort Wiedergabe).")


def run_book_session(
    book_file: Path,
    words_per_chunk: int = 220,
    chunk: int | None = None,
    next_: bool = False,
    repeat: bool = False,
    device: int | None = None,
    minutes: float = 2.0,
    keep_last_audios: int = 10,
    keep_days: int = 0,
    cut_punkt: bool = False,
    read_first: bool = False,
    questions: int = 3,
    prep: str = "enter",
    prep_seconds: int = 90,
    q_seconds: int = 25,
    level: str = "easy",
    retell_seconds: int = 60,
):
    if not book_file.exists():
        raise SystemExit(f"Buchdatei nicht gefunden: {book_file.resolve()}")

    text = load_book_text(book_file)
    chunks = chunk_words(text, words_per_chunk=words_per_chunk)
    if not chunks:
        raise SystemExit("Buchdatei ist leer oder konnte nicht gechunkt werden.")

    idx = get_chunk_index(book_file, len(chunks), chunk, next_, repeat)
    chunk_text = chunks[idx]

    print("\n" + "=" * 80)
    print(f"BOOK: {book_file.name} | Chunk {idx + 1}/{len(chunks)} | ~{words_per_chunk} Wörter")
    print("=" * 80)
    print(chunk_text)
    print("=" * 80)

    topic_base = f"book:{book_file.name}:chunk:{idx + 1}"

    if read_first:
        print("\nMODE=read: Lies den Abschnitt vor.")
        _record_and_transcribe(
            mode="read",
            topic=topic_base,
            source_text=chunk_text,
            device=device,
            minutes=max(0.2, q_seconds / 60.0),
            keep_last_audios=keep_last_audios,
            keep_days=keep_days,
            cut_punkt=cut_punkt,
        )

    _prep_phase(prep=prep, prep_seconds=prep_seconds)

    print("\n" + _with_retell_hint("Wiedergabe: 2–6 Sätze. Gib den Abschnitt in eigenen Worten wieder."))
    print("Bonus (optional): Verwende 1–2 Bonus-Begriffe, wenn möglich.\n")

    bonus_terms = suggest_bonus_terms(chunk_text, None, k=5)
    print("BONUS-Begriffe (optional für Wiedergabe – verwende 1–2, wenn möglich):")
    print(", ".join(bonus_terms) if bonus_terms else "(keine)")
    print()

    print("\nMODE=Wiedergabe: Gib den Abschnitt in eigenen Worten wieder.")
    
    retell_minutes = max(0.1, retell_seconds / 60.0)
    
    retell_audio, _, _ = _record_and_transcribe(
        mode="retell",
        topic=topic_base,
        source_text=chunk_text,
        device=device,
        minutes=retell_minutes,
        keep_last_audios=keep_last_audios,
        keep_days=keep_days,
        cut_punkt=cut_punkt,
        forced_bonus_terms=bonus_terms,
    )
    print(f"Retell-Audio: {retell_audio}")

    qs = ask_questions_default(n=questions, level=level)
    modes = ["q1", "q2", "q3"][:len(qs)]

    for mode, q in zip(modes, qs):
        print("\n" + "-" * 80)
        print(q)
        print(_with_variation_hint(""))
        print("-" * 80)

        forced_bonus = None
        if mode == "q3":
            forced_bonus = suggest_bonus_terms(chunk_text, None, k=5)
            print("BONUS (Pflicht): Verwende 1 dieser Begriffe in deiner Antwort:")
            print(", ".join(forced_bonus) if forced_bonus else "(keine)")
            print()

        audio_path, transcript, payload = _record_and_transcribe(
            mode=mode,
            topic=topic_base,
            source_text=chunk_text + "\n\n" + q,
            device=device,
            minutes=max(0.2, q_seconds / 60.0),
            keep_last_audios=keep_last_audios,
            keep_days=keep_days,
            cut_punkt=cut_punkt,
            forced_bonus_terms=forced_bonus,
        )

        if mode == "q3":
            print()
            print(make_q3_feedback(transcript, payload))


def _record_and_transcribe(
    *,
    mode: str,
    topic: str,
    source_text: str,
    device: int | None,
    minutes: float,
    keep_last_audios: int,
    keep_days: int,
    cut_punkt: bool,
    forced_bonus_terms: list[str] | None = None,
) -> tuple[str, str, dict]:
    from datetime import datetime, UTC

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    out = Path("data/audio") / f"{ts}_{topic.replace(':', '-')}_{mode}.wav"

    try:
        record_mic_to_wav(out_path=out, minutes=minutes, device=device)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        raise SystemExit(0)

    raw = transcribe_with_whisper(str(out))
    transcript = cut_at_punkt(raw) if cut_punkt else normalize_text(raw)

    stats = compute_stats(transcript)

    dur_s = None
    try:
        dur_s = wav_duration_seconds(out)
    except Exception:
        dur_s = None

    # Flags berechnen und genau 1× warnen
    flags = compute_quality_flags(
        mode=mode,
        transcript=transcript,
        stats_obj=stats,
        duration_seconds=dur_s,
    )
    print_quality_warnings(mode=mode, flags=flags)

    payload = stats_to_payload(stats)
    payload["duration_seconds"] = round(dur_s, 2) if dur_s else None
    payload["wpm"] = round(stats.word_count / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

    # Flags IMMER speichern
    payload.update(flags)

    # Target/Bonus nur wo relevant
    if mode in ("retell", "q3"):
        targets = suggest_target_terms(source_text, transcript, k=8)
        payload["target_terms"] = targets
        payload["target_terms_check"] = terms_used(targets, transcript)

        bonus = forced_bonus_terms if forced_bonus_terms is not None else suggest_bonus_terms(source_text, transcript, k=5)
        payload["bonus_terms"] = bonus
        payload["bonus_terms_check"] = terms_used(bonus, transcript)

    if mode == "q3":
        t_low = (transcript or "").lower()
        payload["q3_has_causal"] = ("weil" in t_low) or ("deshalb" in t_low)

    session_id = insert_session(
        topic=topic,
        mode=mode,
        source_text=source_text,
        transcript=transcript,
        stats_payload=payload,
        audio_path=str(out),
    )

    print(f"\nSession gespeichert: id={session_id} | mode={mode}")
    print("TIPP: Fortschritt ansehen mit: python3 sprachapp_main.py report --progress --last 200")
    print(f"Transkript:\n{transcript}\n")

    backend = get_coach_backend()
    resp = backend.generate(
        CoachRequest(
            mode=mode,
            topic=f"{topic}:{mode}",
            source_text=source_text,
            transcript=transcript,
            stats_payload=payload,
        )
    )
    print_coach_block(resp)

    print("Stats:", payload)

    cleanup_audio_retention(Path("data/audio"), keep_last=keep_last_audios, keep_days=int(keep_days or 0))
    return str(out), transcript, payload
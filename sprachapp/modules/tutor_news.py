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


PROGRESS_PATH = Path("data/news_progress.json")


def _news_key(news_file: Path) -> str:
    h = hashlib.sha1(str(news_file.resolve()).encode("utf-8")).hexdigest()[:12]
    return h


def load_news_text(news_file: Path) -> str:
    return news_file.read_text(encoding="utf-8").strip()


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


def get_chunk_index(news_file: Path, total_chunks: int, chunk: int | None, next_: bool, repeat: bool) -> int:
    prog = load_progress()
    key = _news_key(news_file)
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


def ask_questions_default(n: int = 3) -> list[str]:
    base = [
        "Frage 1 (These): Formuliere die Kernaussage in genau 1 Satz.",
        "Frage 2 (Argument): Nenne 2 konkrete Aussagen/Fakten aus dem Abschnitt.",
        "Frage 3 (Begründung): Warum ist die Argumentation/Deutung plausibel? Nutze 'weil/deshalb' in deinem Satz.",
    ]
    return base[:max(1, min(n, len(base)))]

def _prompt_for(level: str, mode: str) -> str:
    level = (level or "easy").strip().lower()
    mode = (mode or "").strip().lower()

    if mode == "retell":
        if level == "easy":
            return "Wiedergabe (leicht): 2–3 Sätze. Was ist passiert?"
        if level == "medium":
            return "Wiedergabe (mittel): 4–6 Sätze. Nenne 3 wichtige Punkte + 1 Detail."
        return "Wiedergabe (schwer): 4–6 Sätze. Struktur: Thema → 3 Punkte → Schluss/Fazit. (Max. 60 Sekunden)"
    
    if mode == "q1":
        if level == "easy":
            return "Q1 (leicht): 1 Satz. Deine These/Meinung."
        if level == "medium":
            return "Q1 (mittel): 2 Sätze. These + kurze Begründung (1× weil/denn)."
        return "Q1 (schwer): 3 Sätze. These + 2 Argumente (klar getrennt)."

    if mode == "q2":
        if level == "easy":
            return "Q2 (leicht): 2 Sätze. Nenne 2 Fakten/Aussagen aus dem Abschnitt."
        if level == "medium":
            return "Q2 (mittel): 3 Sätze. 2 Gründe + 1 Beispiel."
        return "Q2 (schwer): 4 Sätze. 2 Fakten + Beispiel + kurzer Schluss."

    if mode == "q3":
        if level == "easy":
            return "Q3 (leicht): 2 Sätze. Ursache→Wirkung mit weil/deshalb."
        if level == "medium":
            return "Q3 (mittel): 3 Sätze. Ursache→Wirkung + Folge."
        return "Q3 (schwer): 2–3 Sätze. Ursache→Wirkung + Folge. (Genau 1× weil/deshalb/daher)"
    return ""


def _with_retell_hint(text: str, mode: str) -> str:
    mode = (mode or "").strip().lower()
    if mode == "retell":
        return text + "\n→ Vermeide gleiche Formulierungen wie zuvor."
    return text


def _with_variation_hint(text: str, mode: str) -> str:
    mode = (mode or "").strip().lower()
    if mode in ("q1", "q2", "q3"):
        return text + "\n→ Beginne nicht mit demselben Wort wie zuvor."
    return text


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


def run_news_session(
    news_file: Path,
    words_per_chunk: int = 220,
    chunk: int | None = None,
    next_: bool = False,
    repeat: bool = False,
    device: int | None = None,
    minutes: float = 2.0,   # aktuell ungenutzt
    q_seconds: int = 25,
    keep_last_audios: int = 10,
    keep_days: int = 0,
    cut_punkt: bool = False,
    questions: int = 3,
    prep: str = "enter",
    prep_seconds: int = 90,
    level: str = "easy",
    retell_seconds: int = 60,
    read_first: bool = False,  # aktuell ungenutzt, bleibt kompatibel
):
    if not news_file.exists():
        raise SystemExit(f"Newsdatei nicht gefunden: {news_file.resolve()}")

    text = load_news_text(news_file)
    chunks = chunk_words(text, words_per_chunk=words_per_chunk)
    if not chunks:
        raise SystemExit("Newsdatei ist leer oder konnte nicht gechunkt werden.")

    idx = get_chunk_index(news_file, len(chunks), chunk, next_, repeat)
    chunk_text = chunks[idx]

    print("\n" + "=" * 80)
    print(f"NEWS: {news_file.name} | Chunk {idx + 1}/{len(chunks)} | ~{words_per_chunk} Wörter")
    print("=" * 80)
    print(chunk_text)
    print("=" * 80)

    topic_base = f"news:{news_file.name}:chunk:{idx + 1}"

    _prep_phase(prep=prep, prep_seconds=prep_seconds)

    print("\n" + _with_retell_hint(_prompt_for(level, "retell"), "retell"))
    print("Bonus (optional): Verwende 1–2 Bonus-Begriffe, wenn möglich.\n")

    bonus_terms = suggest_bonus_terms(chunk_text, None, k=5)
    print("BONUS-Begriffe (optional bei Wiedergabe – verwende 1–2, wenn möglich):")
    print(", ".join(bonus_terms) if bonus_terms else "(keine)")
    print()

    print("\nMODE=Wiedergabe: Gib den Abschnitt in eigenen Worten wieder.")
    
    retell_minutes = max(0.1, retell_seconds / 60.0)

    _record_and_transcribe(
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

    qs = ask_questions_default(n=questions)
    for i, q in enumerate(qs, start=1):
        print("\n" + "-" * 80)
        print(q)
        print("-" * 80)
        mode = f"q{i}"
        print(_with_variation_hint(_prompt_for(level, mode), mode))

        forced_bonus = None
        if "Begründung" in q:
            forced_bonus = suggest_bonus_terms(chunk_text, None, k=5)
            print("BONUS (Pflicht): Verwende 1 dieser Begriffe in deiner Antwort:")
            print(", ".join(forced_bonus) if forced_bonus else "(keine)")
            print()

        audio_path, transcript, payload = _record_and_transcribe(
            mode=f"q{i}",
            topic=topic_base,
            source_text=chunk_text + "\n\n" + q,
            device=device,
            minutes=max(0.2, q_seconds / 60.0),
            keep_last_audios=keep_last_audios,
            keep_days=keep_days,
            cut_punkt=cut_punkt,
            forced_bonus_terms=forced_bonus,
        )

        if i == 3:
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
    print("Stats:", payload)

    cleanup_audio_retention(Path("data/audio"), keep_last=keep_last_audios, keep_days=int(keep_days or 0))
    return str(out), transcript, payload
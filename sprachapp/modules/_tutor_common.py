from __future__ import annotations

from dataclasses import asdict
from typing import Any


# -----------------------------
# Heuristiken gegen "Geistertext"
# -----------------------------
HALLUCINATION_PHRASES = [
    "das ist der erste teil",
    "das ist der erste mal",
    "das ist der erste",
    "das war's",
    "das war es",
    "ich habe mich nicht verstanden",
    "ich habe mich verstanden",
    "ich bin in der stadt",
    "ich habe jetzt noch ein paar sachen zu tun",
    "ich kann mich nicht erinnern",
    "teil des videos",
]

# minimaler DE-Stopword-Satz (diagnostisch; bewusst klein gehalten)
STOPWORDS_DE = {
    "der", "die", "das", "ein", "eine", "einer", "einem", "einen",
    "und", "oder", "aber", "weil", "deshalb", "dass", "da", "so",
    "ich", "du", "er", "sie", "es", "wir", "ihr", "man",
    "ist", "sind", "war", "waren", "bin", "bist", "hat", "haben",
    "nicht", "noch", "mehr", "mal", "jetzt", "hier", "dort",
    "zu", "zum", "zur", "im", "in", "am", "an", "auf", "von", "mit", "für",
}


def stats_to_payload(stats_obj: Any) -> dict:
    """
    Stats-Objekt robust in ein dict bringen.
    """
    if hasattr(stats_obj, "__dict__"):
        return dict(stats_obj.__dict__)
    try:
        return asdict(stats_obj)  # falls dataclass
    except Exception:
        return {}


def _tokenize_lower(text: str) -> list[str]:
    # einfache Tokenisierung (reicht für Diagnose)
    return [w.strip(".,;:!?\"'()[]{}").lower() for w in (text or "").split() if w.strip()]


def compute_quality_flags(
    *,
    mode: str,
    transcript: str,
    stats_obj: Any,
    duration_seconds: float | None = None,
    min_chars: int = 5,
    min_retell_words: int = 12,
    min_q_words: int = 6,
) -> dict:
    """
    Einheitliche Qualitäts-/Guard-Flags für alle Tutor-Module.

    Flags:
    - asr_empty: sehr kurzes/leer wirkendes Transcript
    - retell_empty: retell ist inhaltlich zu kurz
    - too_short: q1/q2/q3 ist zu kurz
    - suspected_silence: sehr wahrscheinlich Stille oder starke Wiederholung
    - hallucination_hit: Whisper-typischer „Geistertext“ (Standardphrasen / generische Fragmente)
    - stopword_ratio: Anteil Stopwords (Diagnose)
    - low_quality: Sammel-Flag, triggert Warnung (retell_empty/too_short/asr_empty/suspected/hallucination)
    """
    t_raw = transcript or ""
    t = t_raw.strip()
    t_lower = t.lower()

    # Basic counts
    asr_chars = len(t)
    asr_words = len(t.split()) if t else 0

    wc = int(getattr(stats_obj, "word_count", 0) or 0)
    uniq = float(getattr(stats_obj, "unique_ratio", 0.0) or 0.0)

    # sehr konservativ: wenn kaum Zeichen da sind -> praktisch leer
    asr_empty = (asr_chars < min_chars) or (wc == 0)

    # Modusabhängige Mindestlängen
    retell_empty = False
    too_short = False
    if mode == "retell":
        retell_empty = asr_empty or (wc < min_retell_words)
    elif mode.startswith("q"):
        too_short = asr_empty or (wc < min_q_words)

    # Stopword-Quote (Diagnose + Signal)
    words = [w.strip(".,;:!?\"'()[]{}").lower() for w in t.split()]
    words = [w for w in words if w]
    stop_cnt = sum(1 for w in words if w in STOPWORDS_DE)
    stopword_ratio = (stop_cnt / len(words)) if words else 0.0

    # --- Halluzinations-Detektion (kurz + robust) ---
    phrase_hit = False
    for ph in HALLUCINATION_PHRASES:
        if ph and ph in t_lower:
            phrase_hit = True
            break

    # Sehr typische „Schweige/Noise“-Fragmente: kurz + generischer Start
    generic_starts = (
        "das ist der",
        "das ist die",
        "das war's",
        "ich habe jetzt",
        "ich bin in der stadt",
        "das ist der erste",
        "das ist der erste teil",
        "das ist der erste mal",
    )
    generic_fragment = (asr_chars <= 40) and any(t_lower.startswith(gs) for gs in generic_starts)

    # typisch: viele Funktionswörter, wenig Inhalt
    stopword_heavy = (len(words) >= 8 and stopword_ratio >= 0.75)

    hallucination_hit = bool(phrase_hit or stopword_heavy or generic_fragment)

    # --- suspected_silence (Wiederholung/Stille) ---
    suspected_silence = False
    dur = float(duration_seconds) if duration_seconds is not None else None

    # 1) lange Aufnahme, aber praktisch keine echten Wörter
    if dur is not None and dur >= 8.0 and asr_words <= 2:
        suspected_silence = True

    # 2) extrem repetitiv: viele Wörter, sehr wenig unique
    if wc >= 12 and uniq < 0.20:
        suspected_silence = True

    # 3) lange „Geistertexte“ (häufig: Stille → Whisper produziert lange generische Sätze)
    if wc >= 30 and hallucination_hit:
        suspected_silence = True

    # --- low_quality (Warn-Trigger) ---
    low_quality = bool(asr_empty or retell_empty or too_short or suspected_silence or hallucination_hit)

    return {
        "asr_empty": asr_empty,
        "asr_chars": asr_chars,
        "asr_words": asr_words,
        "retell_empty": retell_empty,
        "too_short": too_short,
        "suspected_silence": suspected_silence,
        "hallucination_hit": hallucination_hit,
        "stopword_ratio": round(float(stopword_ratio), 3),
        "low_quality": low_quality,
    }

def print_quality_warnings(*, mode: str, flags: dict) -> None:
    """
    Einheitliche Ausgabe:
    - genau 1 Debug-Zeile [QWARN] pro Aufnahme
    - wenn low_quality=False: keine weitere Ausgabe
    - sonst: genau 1 WARNUNG + genau 1 HINWEIS-Block (Priorität gesteuert)
    """
    retell_empty = bool(flags.get("retell_empty"))
    too_short = bool(flags.get("too_short"))
    suspected = bool(flags.get("suspected_silence"))
    hallucination = bool(flags.get("hallucination_hit"))
    asr_empty = bool(flags.get("asr_empty"))
    low_quality = bool(flags.get("low_quality"))

    # Debug (genau 1x pro Aufnahme)
    print(
        "[QWARN] mode="
        + str(mode)
        + " flags="
        + str(
            {
                k: flags.get(k)
                for k in (
                    "retell_empty",
                    "too_short",
                    "suspected_silence",
                    "hallucination_hit",
                    "asr_empty",
                    "low_quality",
                )
            }
        )
    )

    if not low_quality:
        return

    # Genau 1 WARNUNG
    print("WARNUNG: Antwort wirkt inhaltlich unzuverlässig (ASR/Geistertext/Stille/zu kurz).")

    # Genau 1 HINWEIS-Block, mit Priorität:
    # 1) echte Audio-Probleme/leer
    # 2) Stille/Wiederholung
    # 3) Geistertext
    # 4) zu kurz (retell / q)
    print("HINWEIS:")

    if asr_empty:
        print("- Sprich lauter/näher ans Mikrofon.")
        print("- Prüfe Input-Device (--device).")
        print("- Wenn --cut-punkt: am Ende deutlich 'punkt' sagen oder ohne testen.")
        return

    if suspected:
        print("- Es klingt nach Stille/Wiederholung; Whisper hat evtl. Text geraten.")
        print("- Wiederhole kurz: 1–2 klare Sätze zum Inhalt, näher ans Mikro.")
        return

    if hallucination:
        print("- Whisper hat vermutlich aus Stille/Hintergrundgeräusch Text geraten.")
        print("- Wiederhole 1–2 klare Sätze zum Inhalt (nicht über „Video/Teil“ sprechen).")
        return

    # Fallback: zu kurz (retell/q)
    if mode == "retell" and retell_empty:
        print("- Gib den Inhalt in 2–4 ganzen Sätzen wieder.")
        print("- Starte direkt mit dem Kern (Was ist passiert?).")
        print("- Vermeide Abbruch-Sätze wie „fertig“, „das war’s“.")
        return

    if mode.startswith("q") and too_short:
        print("- Antworte vollständiger (mindestens 1–2 Sätze).")
        print("- Bleib beim Inhalt des Abschnitts/der Frage.")
        return

    # Letzter Fallback (sollte praktisch nie passieren)
    print("- Wiederhole 1–2 klare Sätze zum Inhalt.")
    print("- Sprich ruhig, deutlich und näher ins Mikro.")
    print("- Prüfe Input-Device (--device).")
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
    - hallucination_hit: Whisper-typischer „Geistertext“ (Phrasen / stopword-lastig)
    - stopword_ratio: Anteil Stopwords (Diagnose)
    - low_quality: Sammelflag für "Warnung anzeigen"
    """
    t_raw = transcript or ""
    t = t_raw.strip()
    t_lower = t.lower()

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

    # Stopword Ratio (nur Diagnose/Heuristik)
    words = _tokenize_lower(t)
    stop_ct = sum(1 for w in words if w in STOPWORDS_DE)
    stopword_ratio = (stop_ct / len(words)) if words else 0.0

    # Phrase-Hit (Whisper-Geistertext)
    phrase_hit = any(p in t_lower for p in HALLUCINATION_PHRASES)

    # typisch: viele Funktionswörter, wenig Inhalt (oft bei "… dass ich in der" / generische Floskeln)
    stopword_heavy = (len(words) >= 8 and stopword_ratio >= 0.75)

    hallucination_hit = bool(phrase_hit or stopword_heavy)

    # Silence / Wiederholung grob erkennen
    suspected_silence = False
    dur = float(duration_seconds) if duration_seconds is not None else None

    # (A) lange Aufnahme, aber sehr wenig Worte -> wahrscheinlich Stille
    if dur is not None and dur >= 8.0 and asr_words <= 2:
        suspected_silence = True

    # (B) extrem repetitiv (z.B. viele Wörter, aber sehr wenige unique)
    if wc >= 12 and uniq < 0.20:
        suspected_silence = True

    # ---------------------------------------------------------
    # C3.1 / C3.2: low_quality konsistent ableiten (aber Flags behalten)
    # - low_quality soll "Warnung anzeigen" bedeuten
    # - trotzdem bleiben suspected_silence / hallucination_hit separat erhalten
    # ---------------------------------------------------------
    low_quality = False

    # PRIORITÄT 1: leer/zu kurz
    if asr_empty or retell_empty or too_short:
        low_quality = True
    # PRIORITÄT 2: starke Wiederholung (auch ohne Phrase)
    elif wc >= 40 and uniq <= 0.25:
        low_quality = True
    # PRIORITÄT 3: langer Text + Halluzinations-Hit
    elif wc >= 30 and hallucination_hit:
        low_quality = True
    # PRIORITÄT 4: stopword-lastig
    elif wc >= 12 and stopword_ratio >= 0.75:
        low_quality = True
    # PRIORITÄT 5: heuristisch Stille
    elif suspected_silence:
        low_quality = True

    return {
        "asr_empty": asr_empty,
        "asr_chars": asr_chars,
        "asr_words": asr_words,
        "retell_empty": retell_empty,
        "too_short": too_short,
        "suspected_silence": suspected_silence,
        "hallucination_hit": hallucination_hit,
        "stopword_ratio": round(stopword_ratio, 3),
        "low_quality": low_quality,
    }


def print_quality_warnings(*, mode: str, flags: dict) -> None:
    """
    Einheitliche Warntexte + 1 Debug-Zeile pro Aufnahme.
    Ziel: MAXIMAL EIN Warn-Block pro Aufnahme (keine Doppelwarnungen).
    """
    low_quality = bool(flags.get("low_quality"))
    retell_empty = bool(flags.get("retell_empty"))
    too_short = bool(flags.get("too_short"))
    suspected = bool(flags.get("suspected_silence"))
    hallucination_hit = bool(flags.get("hallucination_hit"))
    asr_empty = bool(flags.get("asr_empty"))

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

    # nichts zu melden
    if not (retell_empty or too_short or asr_empty or low_quality):
        return

    # PRIORITÄT 1: Kurz/leer (und dann STOP)
    if asr_empty or retell_empty or too_short:
        print("WARNUNG: Antwort ist leer oder zu kurz.")

        if mode == "retell" and retell_empty:
            print("HINWEIS (Retell):")
            print("- Gib den Inhalt in 2–4 ganzen Sätzen wieder.")
            print("- Starte direkt mit dem Kern: Was ist passiert/was ist die Aussage?")
            print("- Vermeide reine Abbruch-Sätze wie „fertig“, „das war’s“.")

        if mode.startswith("q") and too_short:
            print("HINWEIS (Frage):")
            print("- Antworte vollständiger (mindestens 1–2 Sätze).")
            print("- Bleib beim Inhalt des Abschnitts/der Frage.")

        if asr_empty:
            print("HINWEIS (Audio/ASR):")
            print("- Sprich lauter/näher ans Mikrofon.")
            print("- Prüfe Input-Device (--device).")
            print("- Wenn --cut-punkt: am Ende deutlich 'punkt' sagen oder ohne testen.")
        return

    # PRIORITÄT 2: Geistertext (und dann STOP)
    if hallucination_hit:
        print("WARNUNG: Antwort wirkt wie ASR-Geistertext (inhaltlich unzuverlässig).")
        print("HINWEIS (ASR-Geistertext):")
        print("- Whisper hat vermutlich aus Stille/Hintergrundgeräusch Text geraten.")
        print("- Wiederhole 1–2 klare Sätze zum Inhalt (nicht über „Video/Teil“ sprechen).")
        return

    # PRIORITÄT 3: Stille/Wiederholung (und dann STOP)
    if suspected:
        print("WARNUNG: Aufnahme wirkt wie Stille/Wiederholung (inhaltlich unzuverlässig).")
        print("HINWEIS (Stille/ASR):")
        print("- Es klingt nach Stille/Hintergrundgeräusch; Whisper hat evtl. Text geraten.")
        print("- Wiederhole kurz: 1–2 klare Sätze, näher ans Mikro.")
        return

    # PRIORITÄT 4: generisch low_quality (Fallback) (und dann STOP)
    if low_quality:
        print("WARNUNG: Antwort wirkt inhaltlich unzuverlässig (ASR/Geistertext/Stille).")
        print("HINWEIS:")
        print("- Wiederhole 1–2 klare Sätze zum Inhalt.")
        print("- Sprich ruhig, deutlich und näher ins Mikro.")
        print("- Prüfe Input-Device (--device).")
        return
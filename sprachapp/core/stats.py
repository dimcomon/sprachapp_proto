
from __future__ import annotations

import re
from dataclasses import dataclass
from collections import Counter
from .text import tokenize_words_de
from typing import List, Dict

FILLER_WORDS_DE = {
    "äh", "ähm", "hm", "also", "sozusagen", "quasi", "halt", "irgendwie", "nunja", "naja"
}

# MVP-Stopwords (bewusst kurz gehalten)
STOPWORDS_DE = {
    "der","die","das","ein","eine","einer","eines","und","oder","aber","auch","zu",
    "im","in","am","an","auf","aus","mit","von","für","dass","den","dem","des",
    "ist","sind","war","waren","wird","werden","wurde","nicht","noch",
    "als","wie","was","wo","wer","wenn","weil","bei","bis","nach","vor","über","unter",
    "gegen","um","sich","es","er","sie","wir","ihr","ich","du","man"
}


@dataclass
class Stats:
    word_count: int
    unique_words: int
    unique_ratio: float
    avg_word_len: float
    filler_count: int


def compute_stats(transcript: str) -> Stats:
    words = tokenize_words_de(transcript)
    if not words:
        return Stats(0, 0, 0.0, 0.0, 0)

    unique = set(words)
    avg_len = sum(len(w) for w in words) / len(words)
    filler = sum(1 for w in words if w in FILLER_WORDS_DE)

    return Stats(
        word_count=len(words),
        unique_words=len(unique),
        unique_ratio=round(len(unique) / len(words), 4),
        avg_word_len=round(avg_len, 2),
        filler_count=filler,
    )


def suggest_target_terms(source_text: str, spoken_text: str | None = None, k: int = 8) -> list[str]:
    """
    Zielbegriffe (Text-nahe Lernwörter), aber stärker gefiltert:
    - Filtert Stopwords
    - Filtert typische alt-/formlastige Endungen (ste/sten/tem/ten/ter/tes)
    - Bonus, wenn Wort im Retell fehlt
    - leichter Bonus für Verben (Endung -en)
    """
    src_words = tokenize_words_de(source_text)

    filtered: list[str] = []
    for w in src_words:
        if len(w) < 5:
            continue
        if w in STOPWORDS_DE:
            continue
        # viele alt-/adjektivische Formen raus
        if w.endswith(("ste", "sten", "tem", "ten", "ter", "tes")):
            continue
        filtered.append(w)

    if not filtered:
        return []

    counts = Counter(filtered)
    spoken_set = set(tokenize_words_de(spoken_text)) if spoken_text else set()

    scored: list[tuple[float, str]] = []
    for w, freq in counts.items():
        score = 1.0 / float(freq)   # seltene Wörter bevorzugen
        if w not in spoken_set:
            score *= 2.0            # Lernbonus: fehlt im Retell
        if w.endswith("en"):
            score *= 1.2            # leichter Verb-Bonus
        scored.append((score, w))

    scored.sort(reverse=True)
    return [w for _, w in scored[:k]]


def suggest_bonus_terms(source_text: str, transcript: str | None = None, k: int = 5) -> list[str]:
    """
    Bonus-Begriffe = aktiv nutzbarer Ausdruck (C1-Style), nicht textnahe Altformen.
    Heuristik:
    - 2 Struktur-/Logik-Wörter (weil/deshalb/dadurch/allerdings)
    - 3 Inhaltswörter aus einer kuratierten Liste, die zum Text passt (Keyword-Matching)
    """
    src = " ".join(tokenize_words_de(source_text))

    connectors = ["weil", "deshalb", "dadurch", "allerdings", "somit"]
    # kuratierte Lernwörter (MVP)
    vocab = [
        ("täusch", "täuschen"),
        ("manipulier", "manipulieren"),
        ("inszenier", "inszenieren"),
        ("plan", "strategie"),
        ("befehl", "anweisen"),
        ("droh", "einschüchtern"),
        ("besitz", "besitz"),
        ("graf", "ausgeben"),
        ("könig", "beeinflussen"),
        ("zauber", "verwandeln"),
        ("bestätig", "bestätigen"),
        ("behaupt", "behaupten"),
    ]

    out: list[str] = []
    # 1) immer 2 Konnektoren anbieten
    out.extend(connectors[:2])

    # 2) passende Inhaltswörter einsammeln
    for key, term in vocab:
        if key in src and term not in out:
            out.append(term)
        if len(out) >= k:
            break

    # 3) fallback: auffüllen mit allgemeinen starken Wörtern
    fallback = ["zusammenhang", "konsequenz", "ziel", "vorteil", "nachteil"]
    for t in fallback:
        if len(out) >= k:
            break
        if t not in out:
            out.append(t)

    return out[:k]


def terms_used(terms: List[str], transcript: str) -> Dict[str, object]:
    if not terms:
        return {"used": [], "missing": [], "rate": None}

    # alle Wörter aus dem Transkript normalisieren
    words = set(re.findall(r"\w+", transcript.lower()))

    used = []
    missing = []

    for term in terms:
        term_norm = term.lower()
        if term_norm in words:
            used.append(term)
        else:
            missing.append(term)

    rate = round(len(used) / len(terms), 3) if terms else None

    return {
        "used": used,
        "missing": missing,
        "rate": rate,
    }
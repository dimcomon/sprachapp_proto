from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CoachInput:
    mode: str
    topic: str | None
    source_text: str | None
    transcript: str
    stats_payload: dict[str, Any]


@dataclass
class CoachOutput:
    feedback_text: str  # reiner Text, später optional TTS


def generate_coach_feedback(inp: CoachInput) -> CoachOutput:
    """
    MVP5-A Stub: Noch keine KI.
    Nutzt nur vorhandene Daten (mode/topic/transcript/stats_payload) für einfache Hinweise.
    Keine neue Qualitätslogik, keine DB-Änderungen.
    """
    flags = {}
    if isinstance(inp.stats_payload, dict):
        flags = {k: inp.stats_payload.get(k) for k in ("asr_empty", "too_short", "suspected_silence", "hallucination_hit", "low_quality")}

    notes: list[str] = []
    if flags.get("asr_empty") is True or flags.get("suspected_silence") is True:
        notes.append("Ich habe dich kaum gehört. Sprich näher ins Mikro und etwas lauter.")
    if flags.get("too_short") is True:
        notes.append("Die Antwort war sehr kurz. Versuche 1–2 klare Sätze mehr.")
    if flags.get("hallucination_hit") is True:
        notes.append("Der Text wirkt unzuverlässig. Wiederhole langsam und deutlich, ohne lange Pausen.")
    if not notes:
        notes.append("Gut. Beim nächsten Versuch: klarer strukturieren und ein kurzes Beispiel nennen.")

    return CoachOutput(feedback_text=" ".join(notes))
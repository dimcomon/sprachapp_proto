from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import os
import re
from sprachapp.core.coach_llm import run_llm_coach

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
    
    def format_coach_output(*, feedback_text: str, score: float | None = None) -> str:
        lines: list[str] = []
        head = "COACH"
        if score is not None:
            head += f" (Score: {score:.2f})"
        lines.append(head + ":")

        # in max. 3 Punkte zerlegen (KI liefert oft Sätze)
        parts = [p.strip() for p in feedback_text.replace("\n", " ").split(".") if p.strip()]
        parts = parts[:3] if parts else [feedback_text.strip()]

        for p in parts:
            # Punkt wieder dranhängen, falls Satz
            if not p.endswith(("!", "?", ".")):
                p += "."
            lines.append(f"- {p}")

        return "\n".join(lines)


def format_coach_output(*, feedback_text: str, score: float | None = None) -> str:
    lines: list[str] = []

    # Header
    head = "COACH"
    if score is not None:
        head += f" (Score: {score:.2f})"
    lines.append(head + ":")

    # --- Clean ---
    clean = (feedback_text or "").replace("\n", " ").strip()

    # Quotes normalisieren/entfernen (damit keine offenen „ hängen bleiben)
    clean = clean.replace("“", "").replace("”", "").replace('"', "")
    clean = clean.replace("„", "").replace("“", "").replace("”", "").replace("‚", "").replace("‘", "")

    # Abkürzungen schützen
    clean = clean.replace("z. B.", "zB").replace("z.B.", "zB")

    # Ellipsen normalisieren
    clean = clean.replace("…", "...")

    # In Sätze schneiden: nach . ! ? oder ...
    parts = re.split(r"(?<=[.!?])\s+|\.{3}\s+", clean)
    parts = [p.strip() for p in parts if p and p.strip()]

    # Falls gar nichts brauchbar: alles als ein Punkt
    if not parts:
        parts = [clean] if clean else ["(kein Feedback)"]

    # Max. 3 Punkte
    parts = parts[:3]

    # Abkürzung zurück
    parts = [p.replace("zB", "z. B.") for p in parts]

    # Bullets bauen
    for p in parts:
        # Endzeichen ergänzen, falls keins da
        if not p.endswith(("!", "?", ".")):
            p += "."
        lines.append(f"- {p}")

    return "\n".join(lines)


def generate_coach_feedback(inp: CoachInput) -> CoachOutput:
    """
    Coach: bevorzugt LLM (wenn aktiviert), sonst Stub-Fallback.
    Keine neue Qualitätslogik, keine DB-Änderungen.
    """

    # LLM nur wenn explizit aktiviert (damit es nicht "aus Versehen" Kosten macht)
    # Aktivieren: export COACH_USE_LLM=1
    use_llm = os.getenv("COACH_USE_LLM", "0").strip() == "1"

    if use_llm:
        try:
            llm = run_llm_coach(
                mode=inp.mode,
                source_text=inp.source_text,
                transcript=inp.transcript,
            )
            # Wenn LLM sauber antwortet, nutzen wir es direkt.
            return CoachOutput(
                feedback_text=format_coach_output(
                    feedback_text=llm.feedback_text,
                    score=llm.score
                )
            )
        except Exception:
            # Fallback ohne Drama
            pass

    # ---- Stub-Fallback (dein bisheriger Code) ----
    flags = {}
    if isinstance(inp.stats_payload, dict):
        flags = {
            k: inp.stats_payload.get(k)
            for k in ("asr_empty", "too_short", "suspected_silence", "hallucination_hit", "low_quality")
        }

    notes: list[str] = []
    if flags.get("asr_empty") is True or flags.get("suspected_silence") is True:
        notes.append("Ich habe dich kaum gehört. Sprich näher ins Mikro und etwas lauter.")
    if flags.get("too_short") is True:
        notes.append("Die Antwort war sehr kurz. Versuche 1–2 klare Sätze mehr.")
    if flags.get("hallucination_hit") is True:
        notes.append("Der Text wirkt unzuverlässig. Wiederhole langsam und deutlich, ohne lange Pausen.")
    if not notes:
        notes.append("Gut. Beim nächsten Versuch: klarer strukturieren und ein kurzes Beispiel nennen.")

    return CoachOutput(
        feedback_text=format_coach_output(
            feedback_text=" ".join(notes),
            score=None
        )
    )

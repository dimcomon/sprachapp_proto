from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

client = OpenAI()

import os
import time
from datetime import datetime, UTC

# --- Runtime Config (env) ---
COACH_LOG = os.getenv("COACH_LOG", "0") == "1"
COACH_TIMEOUT_S = float(os.getenv("COACH_TIMEOUT_S", "12"))
COACH_MAX_OUTPUT_TOKENS = int(os.getenv("COACH_MAX_OUTPUT_TOKENS", "250"))

# Optional: harter Deckel pro Prozess (Kostenkontrolle, minimal)
COACH_MAX_CALLS = int(os.getenv("COACH_MAX_CALLS", "0"))  # 0 = aus
_COACH_CALLS = 0


def _log_event(*, mode: str, success: bool, latency_ms: int, reason: str = "") -> None:
    if not COACH_LOG:
        return
    ts = datetime.now(UTC).isoformat()
    # Keine Inhalte loggen!
    tail = f" reason={reason}" if reason else ""
    print(f"\n[LLM-LOG] ts={ts} mode={mode} success={success} latency_ms={latency_ms}{tail}\n")

@dataclass
class LLMCoachResult:
    score: Optional[float]          # 0.0 – 1.0
    feedback_text: str              # Text für Nutzer
    reasoning: Optional[str] = None # optional, intern


def _build_prompt(*, mode: str, source_text: Optional[str], transcript: str) -> str:
    src = source_text.strip() if isinstance(source_text, str) else ""
    tr = transcript.strip()

    return (
        "Du bist ein Sprachcoach für Deutsch. Bewerte die Antwortqualität und gib kurzes, konkretes Feedback.\n"
        "Regeln:\n"
        "- Antworte AUSSCHLIESSLICH als JSON-Objekt.\n"
        "- JSON-Keys: score (0.0-1.0 Zahl), feedback_text (max 3 Sätze, deutsch), reasoning (optional).\n"
        "- Keine Markdown-Backticks, keine zusätzlichen Texte.\n"
        "- Keine neue Heuristik erfinden; bewerte nur das Gesagte.\n\n"
        f"MODE: {mode}\n"
        f"SOURCE_TEXT:\n{src}\n\n"
        f"TRANSCRIPT:\n{tr}\n"
    )


def run_llm_coach(
    *,
    mode: str,
    source_text: Optional[str],
    transcript: str,
) -> LLMCoachResult:
    prompt = _build_prompt(mode=mode, source_text=source_text, transcript=transcript)

    global _COACH_CALLS
    if COACH_MAX_CALLS > 0 and _COACH_CALLS >= COACH_MAX_CALLS:
        _log_event(mode=mode, success=False, latency_ms=0, reason="max_calls")
        return LLMCoachResult(
            score=None,
            feedback_text="KI-Coach ist für diese Session begrenzt (Limit erreicht).",
            reasoning="max_calls",
        )

    t0 = time.perf_counter()
    try:
        _COACH_CALLS += 1
        resp = client.responses.create(
            model="gpt-5.2",
            input=prompt,
            timeout=COACH_TIMEOUT_S,
            max_output_tokens=COACH_MAX_OUTPUT_TOKENS,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        _log_event(mode=mode, success=True, latency_ms=latency_ms)
    except Exception as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        # Reason grob klassifizieren, ohne Inhalte
        msg = str(e).lower()
        reason = "error"
        if "timeout" in msg:
            reason = "timeout"
        elif "unauthorized" in msg or "401" in msg:
            reason = "auth"
        elif "quota" in msg or "billing" in msg or "insufficient" in msg or "402" in msg:
            reason = "billing"
        _log_event(mode=mode, success=False, latency_ms=latency_ms, reason=reason)

        return LLMCoachResult(
            score=None,
            feedback_text="KI-Coach aktuell nicht erreichbar. Bitte später erneut versuchen.",
            reasoning=reason,
        )

    text = (resp.output_text or "").strip()

    # Robust: JSON extrahieren
    try:
        data = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except Exception:
                data = None
        else:
            data = None

    if not isinstance(data, dict):
        return LLMCoachResult(
            score=None,
            feedback_text="KI-Coach: Antwort konnte nicht ausgewertet werden.",
            reasoning=text[:500] if text else None,
        )

    score = data.get("score")
    feedback_text = data.get("feedback_text") or ""
    reasoning = data.get("reasoning")

    # Minimal validieren
    try:
        score = float(score) if score is not None else None
    except Exception:
        score = None

    if not isinstance(feedback_text, str) or not feedback_text.strip():
        feedback_text = "KI-Coach: Kein verwertbares Feedback erhalten."

    return LLMCoachResult(
        score=score,
        feedback_text=feedback_text.strip(),
        reasoning=reasoning if isinstance(reasoning, str) else None,
    )
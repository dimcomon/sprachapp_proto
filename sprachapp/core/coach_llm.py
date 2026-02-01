from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

client = OpenAI()


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

    # Responses API (empfohlen)  [oai_citation:3‡OpenAI Plattform](https://platform.openai.com/docs/api-reference/responses?utm_source=chatgpt.com)
    resp = client.responses.create(
        model="gpt-5.2",
        input=prompt,
    )

    text = (resp.output_text or "").strip()

    # Robust: falls Modell doch Text drumrum schreibt, versuchen wir das erste JSON zu extrahieren
    try:
        data = json.loads(text)
    except Exception:
        # Fallback: naive Extraktion von erstem {...}
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            return LLMCoachResult(
                score=None,
                feedback_text="KI-Coach: Antwort konnte nicht ausgewertet werden (ungültiges Format).",
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
        feedback_text = "KI-Coach: Kein Feedback erhalten."

    return LLMCoachResult(score=score, feedback_text=feedback_text.strip(), reasoning=reasoning if isinstance(reasoning, str) else None)
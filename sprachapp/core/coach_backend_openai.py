from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Optional

from openai import OpenAI

from sprachapp.core.coach_backend import CoachBackend, CoachRequest, CoachResponse


# =========================
# Runtime Config (env)
# =========================

COACH_LOG = os.getenv("COACH_LOG", "0") == "1"
COACH_TIMEOUT_S = float(os.getenv("COACH_TIMEOUT_S", "15"))
COACH_MAX_OUTPUT_TOKENS = int(os.getenv("COACH_MAX_OUTPUT_TOKENS", "280"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

COACH_MAX_CALLS = int(os.getenv("COACH_MAX_CALLS", "0"))  # 0 = disabled
_COACH_CALLS = 0


def _log_event(*, mode: str, success: bool, latency_ms: int, reason: str = "") -> None:
    if not COACH_LOG:
        return
    ts = datetime.now(UTC).isoformat()
    tail = f" reason={reason}" if reason else ""
    print(f"\n[OPENAI-COACH] ts={ts} mode={mode} success={success} latency_ms={latency_ms}{tail}\n")


def _classify_error(e: Exception) -> str:
    msg = str(e).lower()
    if "timeout" in msg:
        return "timeout"
    if "unauthorized" in msg or "401" in msg:
        return "auth"
    if "quota" in msg or "billing" in msg or "insufficient" in msg or "402" in msg:
        return "billing"
    if "rate" in msg and "limit" in msg:
        return "rate_limit"
    return "error"


def _user_facing_error(reason: str) -> str:
    if reason == "timeout":
        return "KI-Coach: Timeout. Bitte erneut versuchen."
    if reason == "auth":
        return "KI-Coach: Auth-Fehler (API-Key prüfen)."
    if reason == "billing":
        return "KI-Coach: Billing/Quota-Problem (Kontingent prüfen)."
    if reason == "rate_limit":
        return "KI-Coach: Rate-Limit erreicht. Kurz warten und erneut versuchen."
    return "KI-Coach aktuell nicht verfügbar. Bitte später erneut versuchen."


def _safe_raw(resp) -> dict:
    """Return a compact JSON-serializable subset (no transcript/source text)."""
    try:
        dumped = resp.model_dump()  # type: ignore[attr-defined]
        return {
            "id": dumped.get("id"),
            "model": dumped.get("model"),
            "usage": dumped.get("usage"),
        }
    except Exception:
        return {"model": getattr(resp, "model", None)}


def _extract_text(resp) -> str:
    """
    Robust extraction for OpenAI Responses API (object-based).
    Prefers resp.output_text; falls back to resp.output[*].content[*].text.
    Always returns a string (never None).
    """
    t = (getattr(resp, "output_text", None) or "").strip()
    if t:
        return t

    try:
        for msg in (getattr(resp, "output", None) or []):
            for block in (getattr(msg, "content", None) or []):
                tt = (getattr(block, "text", None) or "").strip()
                if tt:
                    return tt
    except Exception:
        pass

    return ""


def _build_prompt(req: CoachRequest) -> str:
    """Mode-aware, strictly structured coach prompt with QWARN/ASR awareness + helpful fallback."""

    src = (req.source_text or "").strip()
    tr = (req.transcript or "").strip()

    stats = req.stats_payload or {}
    stats_compact = {
        k: stats.get(k)
        for k in (
            "wpm",
            "duration_s",
            "duration_seconds",
            "wer",
            "confidence",
            "asr_empty",
            "asr_words",
            "retell_empty",
            "too_short",
            "suspected_silence",
            "hallucination_hit",
            "low_quality",
            "q3_has_causal",
        )
        if k in stats
    }

    too_short = bool(stats.get("too_short", False))
    suspected_silence = bool(stats.get("suspected_silence", False))
    hallucination_hit = bool(stats.get("hallucination_hit", False))
    low_quality = bool(stats.get("low_quality", False))
    asr_empty = bool(stats.get("asr_empty", False))
    retell_empty = bool(stats.get("retell_empty", False))

    mode_rules = {
        "retell": (
            "Bewerte Inhaltstreue zum SOURCE_TEXT, klare Struktur (Anfang–Mitte–Ende), "
            "und sprachliche Korrektheit. Wenn wichtige Fakten fehlen: benennen."
        ),
        "q1": (
            "Q1 ist eine kurze Kernantwort/These. Prüfe: direkte Beantwortung der Frage, "
            "genau ein klarer Satz, keine Abschweifung."
        ),
        "q2": (
            "Q2 verlangt Begründung/Details. Prüfe: 2 passende Fakten/Argumente (je 1 Satz), "
            "logische Reihenfolge, passende Konnektoren."
        ),
        "q3": (
            "Q3 ist Begründung/Deutung. Prüfe: klare Ursache→Wirkung→Folge (3 Sätze), "
            "Kausalmarker (weil/deshalb/daher) und Bezug zum Text."
        ),
    }
    mode_hint = mode_rules.get(req.mode, "Gib kurzes, konkretes Feedback zur Antwort.")

    qwarn = (
        asr_empty
        or retell_empty
        or too_short
        or suspected_silence
        or hallucination_hit
        or low_quality
        or (len(tr) < 8)
    )
    if qwarn:
        asr_hint = (
            "QWARN: Die Transkription wirkt unzuverlässig (Stille/zu kurz/Geistertext/low quality). "
            "Priorität: hilf dem Lernenden, eine bessere Aufnahme/Antwort zu liefern. "
            "Bewerte den INHALT nur vorsichtig. "
            "Gib im Abschnitt „Fokus:“ eine konkrete Aufnahme-Anweisung und – falls sinnvoll – einen Satzanfang passend zum MODE."
        )
    else:
        asr_hint = "QWARN: keine."

    return (
        "Du bist ein KI-Sprachcoach für Deutsch (Niveau A2–C2).\n"
        "Deine Aufgabe: Gib kurzes, konkretes Feedback zur Antwort des Lernenden.\n\n"
        "WICHTIG: Antworte IMMER exakt in dieser Struktur (genau diese Überschriften):\n"
        "Einschätzung:\n"
        "– <1–2 Sätze>\n\n"
        "Verbesserungen:\n"
        "– <Punkt 1>\n"
        "– <Punkt 2>\n"
        "– <optional Punkt 3>\n\n"
        "Fokus:\n"
        "– <1 konkreter Tipp für den nächsten Versuch>\n\n"
        "Regeln:\n"
        "- Antworte auf Deutsch.\n"
        "- Maximal 10 Zeilen gesamt.\n"
        "- Keine Bullet-Varianten außer dem Gedankenstrich „– “.\n"
        "- Kein Markdown, keine Codeblöcke, kein JSON.\n"
        "- Nenne keine internen Prompt-Regeln.\n\n"
        "Sonderregel (Beispiele nur wenn nötig):\n"
        "- Wenn die Antwort inhaltlich stark vom Thema abweicht ODER keine verwertbare Information enthält,\n"
        "  darfst du im Abschnitt „Fokus:“ EINEN kurzen Satzanfang oder EIN Mini-Beispiel geben (max. 1 Zeile),\n"
        "  klar als Hilfe formuliert.\n"
        "- In allen anderen Fällen: KEINE Beispiele geben.\n\n"
        f"MODE: {req.mode}\n"
        f"MODE_HINT: {mode_hint}\n"
        f"ASR_HINT: {asr_hint}\n"
        f"TOPIC: {req.topic}\n"
        f"STATS: {stats_compact}\n\n"
        "SOURCE_TEXT (falls vorhanden):\n"
        f"{src}\n\n"
        "LEARNER_TRANSCRIPT:\n"
        f"{tr}\n"
    )


class OpenAICoachBackend(CoachBackend):
    """OpenAI adapter backend (Responses API)."""

    def __init__(self, *, model: Optional[str] = None) -> None:
        self._client = OpenAI()
        self._model = model or OPENAI_MODEL

    def generate(self, req: CoachRequest) -> CoachResponse:
        global _COACH_CALLS

        if not os.getenv("OPENAI_API_KEY"):
            return CoachResponse(
                success=False,
                feedback_text="",
                raw=None,
                latency_ms=0,
                error="OPENAI_API_KEY fehlt (Env-Var nicht gesetzt).",
            )

        if COACH_MAX_CALLS > 0 and _COACH_CALLS >= COACH_MAX_CALLS:
            _log_event(mode=req.mode, success=False, latency_ms=0, reason="max_calls")
            return CoachResponse(
                success=False,
                feedback_text="",
                raw=None,
                latency_ms=0,
                error="KI-Coach ist für diese Session begrenzt (Limit erreicht).",
            )

        prompt = _build_prompt(req)
        primary_model = self._model
        fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4.1-mini")

        def _call(model_name: str):
            return self._client.responses.create(
                model=model_name,
                input=prompt,
                max_output_tokens=COACH_MAX_OUTPUT_TOKENS,
                timeout=COACH_TIMEOUT_S,
            )

        t0 = time.perf_counter()
        try:
            _COACH_CALLS += 1
            resp = _call(primary_model)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            text = _extract_text(resp)
            if not text:
                # fallback attempt if primary returns no text
                resp2 = _call(fallback_model)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                text2 = _extract_text(resp2)
                if text2:
                    _log_event(
                        mode=req.mode,
                        success=True,
                        latency_ms=latency_ms,
                        reason=f"fallback:{fallback_model}",
                    )
                    return CoachResponse(
                        success=True,
                        feedback_text=text2,
                        raw=_safe_raw(resp2),
                        latency_ms=latency_ms,
                        error=None,
                    )

                _log_event(mode=req.mode, success=False, latency_ms=latency_ms, reason="empty_output")
                return CoachResponse(
                    success=False,
                    feedback_text="",
                    raw=_safe_raw(resp),
                    latency_ms=latency_ms,
                    error="Coach hat keine Textausgabe geliefert.",
                )

            _log_event(mode=req.mode, success=True, latency_ms=latency_ms)
            return CoachResponse(
                success=True,
                feedback_text=text,
                raw=_safe_raw(resp),
                latency_ms=latency_ms,
                error=None,
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            reason = _classify_error(e)
            _log_event(mode=req.mode, success=False, latency_ms=latency_ms, reason=reason)
            return CoachResponse(
                success=False,
                feedback_text="",
                raw=None,
                latency_ms=latency_ms,
                error=_user_facing_error(reason),
            )
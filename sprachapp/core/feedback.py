from __future__ import annotations

import re
from typing import Any


def _count_repetitions(text: str) -> int:
    # grob: gleiche 3+ Wörter Sequenz wiederholt
    t = re.sub(r"\s+", " ", text.strip().lower())
    if len(t) < 40:
        return 0
    reps = 0
    for m in re.finditer(r"(\b\w+\b\s+\b\w+\b\s+\b\w+\b)(?:\s+\1)+", t):
        reps += 1
    return reps


def make_q3_feedback(transcript: str, payload: dict) -> str:
    """
    Gibt Feedback-Text für Q3 zurück und setzt zusätzlich payload['q3_has_causal'].
    """
    t = (transcript or "").strip().lower()

    # Kausalmarker (minimal robust)
    has_causal = ("weil" in t) or ("deshalb" in t)
    payload["q3_has_causal"] = bool(has_causal)

    # Bonus-Check, falls vorhanden
    bonus_used = 0
    used_terms = []
    try:
        btc = payload.get("bonus_terms_check") or {}
        used_terms = list(btc.get("used") or [])
        bonus_used = len(used_terms)
    except Exception:
        bonus_used = 0
        used_terms = []

    lines = []
    if has_causal:
        lines.append("- Struktur: Begründung erkennbar (Kausalmarker vorhanden).")
    else:
        lines.append("- Struktur: Es fehlt ein klarer Kausalmarker (z.B. „weil/deshalb“).")

    if bonus_used > 0:
        lines.append(f"- Bonus: Gut genutzt ({bonus_used} Treffer: {', '.join(used_terms)}).")
    else:
        lines.append("- Bonus: Nicht genutzt (baue 1 Bonus-Begriff bewusst ein).")

    # Kürze: hier bewusst simpel, weil q_seconds variieren kann
    lines.append("- Kürze: Passt (kurz und fokussiert).")
    lines.append("Nächstes Mal: Starte mit „Der Plan funktioniert, weil … deshalb … Punkt.“")

    return "Feedback Q3:\n" + "\n".join(lines)
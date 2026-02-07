from __future__ import annotations

def print_coach_block(coach_out) -> None:
    """
    Einheitliche Ausgabe für CoachResponse (Mock/OpenAI) und alte dict-Formate.
    """
    print("\n--- COACH-FEEDBACK ---")

    # Neu: CoachResponse (Attribute-basiert)
    if hasattr(coach_out, "success") and hasattr(coach_out, "feedback_text"):
        if getattr(coach_out, "success", False):
            text = (getattr(coach_out, "feedback_text", "") or "").strip()
            print(text if text else "(kein Feedback)")
        else:
            err = (getattr(coach_out, "error", "") or "").strip()
            print(f"(Fehler) {err if err else 'Coach nicht verfügbar.'}")
        print()
        return

    # Alt: dict-Fallback
    if isinstance(coach_out, dict):
        ok = bool(coach_out.get("success", False))
        if ok:
            text = str(coach_out.get("feedback_text", "") or "").strip()
            print(text if text else "(kein Feedback)")
        else:
            err = str(coach_out.get("error", "") or "").strip()
            print(f"(Fehler) {err if err else 'Coach nicht verfügbar.'}")
        print()
        return

    # Unbekannt
    print("(Fehler) Unbekanntes Coach-Format.")
    print()
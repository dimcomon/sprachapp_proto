from __future__ import annotations


def print_coach_block(coach_out) -> None:
    print("\n--- COACH-FEEDBACK ---")

    # 1) CoachResponse (normaler Fall)
    if hasattr(coach_out, "success") and hasattr(coach_out, "feedback_text"):
        if coach_out.success:
            text = (coach_out.feedback_text or "").strip()
            print(text if text else "(kein Feedback)")
        else:
            err = (getattr(coach_out, "error", "") or "").strip()
            print(f"(Fehler) {err if err else 'Coach nicht verfügbar.'}")
        print()
        return

    # 2) dict-Fallback
    if isinstance(coach_out, dict):
        if coach_out.get("success"):
            print((coach_out.get("feedback_text") or "").strip())
        else:
            print(f"(Fehler) {coach_out.get('error', 'Coach nicht verfügbar.')}")
        print()
        return

    # 3) String direkt
    if isinstance(coach_out, str):
        print(coach_out.strip() if coach_out.strip() else "(kein Feedback)")
        print()
        return

    # 4) OpenAI Responses API Objekt
    if hasattr(coach_out, "output_text"):
        text = (coach_out.output_text or "").strip()
        print(text if text else "(Fehler) output_text leer.")
        print()
        return

    # 5) Letzter Rettungsanker: alles zu String
    try:
        text = str(coach_out).strip()
        print(text if text else "(Fehler) Leere Coach-Antwort.")
        print()
        return
    except Exception:
        pass

    print("(Fehler) Unbekanntes Coach-Format.")
    print()
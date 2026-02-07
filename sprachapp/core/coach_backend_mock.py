from __future__ import annotations
from typing import Optional
from time import time

from sprachapp.core.coach_backend import CoachBackend, CoachRequest, CoachResponse


class MockCoachBackend(CoachBackend):
    def generate(self, req: CoachRequest) -> CoachResponse:
        start = time()
        text = (
            f"(MOCK) Feedback für {req.mode}: "
            "Antwort ist verständlich. Achte auf Kürze und klare Struktur."
        )
        return CoachResponse(
            success=True,
            feedback_text=text,
            raw={"mock": True},
            latency_ms=int((time() - start) * 1000),
            error=None,
        )
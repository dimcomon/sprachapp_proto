from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


# =========================
# Input / Output Datamodels
# =========================

@dataclass
class CoachRequest:
    mode: str                 # retell | q1 | q2 | q3
    topic: str
    source_text: Optional[str]
    transcript: str
    stats_payload: dict


@dataclass
class CoachResponse:
    success: bool
    feedback_text: str        # für Anzeige (CLI / App)
    raw: Optional[dict] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# =========================
# Backend Interface
# =========================

class CoachBackend(Protocol):
    def generate(self, req: CoachRequest) -> CoachResponse:
        """Erzeugt Coach-Feedback für eine Session."""
        ...
from __future__ import annotations
import os

from sprachapp.core.coach_backend import CoachBackend
from sprachapp.core.coach_backend_mock import MockCoachBackend


def get_coach_backend() -> CoachBackend:
    """
    Wählt das Coach-Backend per Env-Flag.
    COACH_BACKEND=mock | openai
    Default: mock
    """
    backend = os.getenv("COACH_BACKEND", "mock").lower()

    if backend == "openai":
        # Platzhalter – wird in MVP6-B implementiert
        raise NotImplementedError("OpenAI-Backend folgt in MVP6-B")

    # Default
    return MockCoachBackend()
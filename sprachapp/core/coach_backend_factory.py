from __future__ import annotations

import os

from sprachapp.core.coach_backend import CoachBackend
from sprachapp.core.coach_backend_mock import MockCoachBackend


def get_coach_backend() -> CoachBackend:
    """Wählt das Coach-Backend per Env-Flag.
    COACH_BACKEND=mock | openai
    Default: mock
    """
    print("DEBUG factory COACH_BACKEND =", os.getenv("COACH_BACKEND"))

    backend = os.getenv("COACH_BACKEND", "mock").lower()

    if backend == "openai":
        # Lazy import so Mock can run without the OpenAI dependency installed.
        from sprachapp.core.coach_backend_openai import OpenAICoachBackend

        return OpenAICoachBackend()

    return MockCoachBackend()
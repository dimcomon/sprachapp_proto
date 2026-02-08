# sprachapp_main.py
from __future__ import annotations

from pathlib import Path
import os

# Auto-load env vars from sprachapp.env (if present)
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is None:
        return

    base = Path(__file__).resolve().parent

    # 1) Projekt-Root (./sprachapp.env)
    candidates = [
        base / "sprachapp.env",
        # 2) Separater Secrets-Ordner relativ zum Projekt
        base.parent.parent / "sprachappKeys" / ".env",
    ]

    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path, override=False)
            break


def main() -> None:
    _load_env()
    from sprachapp.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
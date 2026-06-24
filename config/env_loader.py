"""Environment loading helpers.

Secrets should live outside the project tree. For local development, place them
in ~/.ai-juejin-toutiao/.env.local or point AI_JUEJIN_ENV_FILE at a private file.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_project_env() -> None:
    explicit = os.getenv("AI_JUEJIN_ENV_FILE")
    if explicit:
        load_dotenv(explicit)
        return

    external = Path.home() / ".ai-juejin-toutiao" / ".env.local"
    if external.exists():
        load_dotenv(external)
    load_dotenv()

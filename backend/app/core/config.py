"""Settings of the web application itself. Database and cache connections are configured in backend.app.db.session
and backend.app.core.cache; the agent's models and retrieval in agent.config."""
import os

from backend.app.core.env import load_project_env

load_project_env()


def _csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


cors_allowed_origins = _csv_env(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
)
cors_allow_credentials = _bool_env("CORS_ALLOW_CREDENTIALS", True)
if cors_allow_credentials and cors_allowed_origins == ["*"]:
    raise RuntimeError("CORS_ALLOW_CREDENTIALS=true cannot be used with wildcard CORS_ALLOWED_ORIGINS")

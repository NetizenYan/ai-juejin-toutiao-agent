"""Small local secret hygiene check.

The scanner reports locations and variable names only. It does not print secret
values. It is intentionally conservative and focused on this repository's known
incident patterns.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "tests",
}
TEXT_SUFFIXES = {
    ".env",
    ".example",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
SENSITIVE_KEYS = (
    "API_KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
SAFE_VALUES = {
    "",
    "ollama",
    "not-needed",
    "<set in local .env or secret manager>",
    "<new-strong-password>",
}
BLOCKING_FIXED_STRINGS = (
    "root:123456",
    'REDIS_PASSWORD = "0813"',
    "DEBUG_MODE = True",
    'allow_origins=["*"]',
    "route.continue_",
    "page.goto(",
    "token='{self.token}'",
)
IGNORED_FILES = {
    "scripts/security_secret_scan.py",
}
IGNORED_KEYS = {
    "CONFIRMATION_TOKEN",
    "ROLLBACK_CONFIRMATION_TOKEN",
}
SECRET_ASSIGNMENT_RE = re.compile(
    r"^\s*(?P<key>[A-Z][A-Z0-9_]*(?:API_KEY|PASSWORD|SECRET|TOKEN)[A-Z0-9_]*)\s*=\s*(?P<value>.+?)\s*$"
)


def _is_ignored(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return rel in IGNORED_FILES or any(part in IGNORED_PARTS for part in path.parts)


def _is_text_candidate(path: Path) -> bool:
    if path.name == ".env":
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def _redacted_hit(path: Path, line_no: int, reason: str) -> str:
    rel = path.relative_to(ROOT)
    return f"{rel}:{line_no}: {reason}"


def _scan_file(path: Path) -> list[str]:
    hits: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return hits

    for line_no, line in enumerate(lines, start=1):
        for needle in BLOCKING_FIXED_STRINGS:
            if needle in line:
                hits.append(_redacted_hit(path, line_no, f"blocking pattern `{needle}`"))

        match = SECRET_ASSIGNMENT_RE.match(line)
        if not match:
            continue
        key = match.group("key")
        if key in IGNORED_KEYS or key.endswith("_SET"):
            continue
        raw_value = match.group("value").strip()
        if "#" in raw_value and not raw_value.startswith(("'", '"')):
            raw_value = raw_value.split("#", 1)[0].strip()
        if raw_value.startswith("os.getenv("):
            continue
        raw_value = raw_value.strip('"').strip("'")
        if not any(marker in key for marker in SENSITIVE_KEYS):
            continue
        if raw_value in SAFE_VALUES or raw_value.startswith("<"):
            continue
        if path.name == ".env.example" and raw_value in {"postgres", "localhost"}:
            hits.append(_redacted_hit(path, line_no, f"example file has unsafe default for `{key}`"))
        elif path.name != ".env.example":
            hits.append(_redacted_hit(path, line_no, f"possible committed secret assignment `{key}`"))
    return hits


def main() -> int:
    hits: list[str] = []
    if (ROOT / ".env").exists():
        hits.append(".env:0: project-root .env must not exist")

    for path in ROOT.rglob("*"):
        if not path.is_file() or _is_ignored(path) or not _is_text_candidate(path):
            continue
        hits.extend(_scan_file(path))

    if hits:
        print("Secret hygiene check failed:")
        for hit in hits:
            print(f"- {hit}")
        return 1
    print("Secret hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Load KEY=value pairs from a .env file at the repo root into os.environ.

Lets users keep OPENAI_API_KEY in deckengine/.env instead of remembering to
set it in every terminal. Existing environment variables always win.
(.env is gitignored — never commit keys.)
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_env(path: Path | None = None) -> int:
    p = path or (REPO / ".env")
    if not p.is_file():
        return 0
    loaded = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded

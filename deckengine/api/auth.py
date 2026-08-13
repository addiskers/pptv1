"""Session auth + per-user deck quota for the DeckEngine UI.

Users live in data/users.json (PBKDF2-hashed passwords, per-user quota —
default 1 deck). Sessions are HMAC-signed cookies; the signing secret comes
from DECKENGINE_SECRET or an auto-generated data/.secret (gitignored).

Escape hatches:
- X-API-Key matching DECKENGINE_API_KEY -> service identity "api" (no quota)
- DECKENGINE_AUTH=0 -> identity "dev" (local development / tests)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import HTTPException, Request

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data"
USERS_FILE = DATA_DIR / "users.json"
SECRET_FILE = DATA_DIR / ".secret"
SESSION_COOKIE = "dk_session"
SESSION_TTL = 7 * 24 * 3600
_ITER = 200_000
_SERVICE_IDS = ("api", "dev")


def _secret() -> bytes:
    env = os.environ.get("DECKENGINE_SECRET")
    if env:
        return env.encode()
    if SECRET_FILE.is_file():
        return SECRET_FILE.read_bytes()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(s)
    return s


def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), _ITER)
    return f"pbkdf2_sha256${_ITER}${salt}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        cand = hashlib.pbkdf2_hmac("sha256", pw.encode(),
                                   bytes.fromhex(salt), int(it))
        return hmac.compare_digest(cand.hex(), h)
    except Exception:  # malformed record never authenticates
        return False


def load_users() -> dict:
    if USERS_FILE.is_file():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {"users": {}}


def get_user(email: str) -> dict | None:
    return load_users().get("users", {}).get(email.lower().strip())


def quota_for(email: str) -> int:
    u = get_user(email)
    return int(u.get("quota", 1)) if u else 0


def is_service(identity: str) -> bool:
    return identity in _SERVICE_IDS


def make_session(email: str) -> str:
    exp = int(time.time()) + SESSION_TTL
    payload = f"{base64.urlsafe_b64encode(email.encode()).decode()}.{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_session(token: str) -> str | None:
    try:
        b64, exp, sig = token.rsplit(".", 2)
        payload = f"{b64}.{exp}"
        want = hmac.new(_secret(), payload.encode(),
                        hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want, sig) or int(exp) < time.time():
            return None
        email = base64.urlsafe_b64decode(b64.encode()).decode()
        return email if get_user(email) else None
    except Exception:
        return None


def identity_of(request: Request) -> str | None:
    """Resolved identity or None: user email, 'api' (key match), or 'dev'
    (auth disabled)."""
    expected = os.environ.get("DECKENGINE_API_KEY")
    if expected and request.headers.get("x-api-key") == expected:
        return "api"
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        email = read_session(tok)
        if email:
            return email
    if os.environ.get("DECKENGINE_AUTH") == "0":
        return "dev"
    return None


def current_user(request: Request) -> str:
    """FastAPI dependency: 401 when nobody is logged in."""
    identity = identity_of(request)
    if identity is None:
        raise HTTPException(401, "login required")
    return identity

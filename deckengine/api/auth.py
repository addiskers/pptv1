"""Session auth + per-user deck quota for the DeckEngine UI.

Users live in data/users.json (per-user quota — default 2 decks).
Authentication is OTP-based: user enters email, receives a 6-digit code,
enters it to sign in or sign up.

Sessions are HMAC-signed cookies; the signing secret comes from
DECKENGINE_SECRET or an auto-generated data/.secret (gitignored).

OTP delivery uses SMTP — configure via env vars:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM

Escape hatches:
- X-API-Key matching DECKENGINE_API_KEY -> service identity "api" (no quota)
- DECKENGINE_AUTH=0 -> identity "dev" (local development / tests)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from fastapi import HTTPException, Request

log = logging.getLogger("deckengine.auth")

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data"
USERS_FILE = DATA_DIR / "users.json"
SECRET_FILE = DATA_DIR / ".secret"
SESSION_COOKIE = "dk_session"
SESSION_TTL = 7 * 24 * 3600
DEFAULT_QUOTA = 2
_SERVICE_IDS = ("api", "dev")

# OTP store: {email: {"code": "123456", "expires": unix_ts, "attempts": int}}
_OTP_STORE: dict[str, dict] = {}
OTP_TTL = 300          # 5 minutes
OTP_LENGTH = 6
OTP_MAX_ATTEMPTS = 5   # lockout after N wrong guesses


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


# -- user persistence -------------------------------------------------------

def load_users() -> dict:
    if USERS_FILE.is_file():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {"users": {}}


def _save_users(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def get_user(email: str) -> dict | None:
    return load_users().get("users", {}).get(email.lower().strip())


def create_user(email: str) -> dict:
    """Create a new user with the default quota. Returns the user dict."""
    email = email.lower().strip()
    data = load_users()
    if email in data.get("users", {}):
        return data["users"][email]
    data.setdefault("users", {})[email] = {"quota": DEFAULT_QUOTA}
    _save_users(data)
    return data["users"][email]


def user_exists(email: str) -> bool:
    return get_user(email) is not None


def quota_for(email: str) -> int:
    u = get_user(email)
    return int(u.get("quota", DEFAULT_QUOTA)) if u else 0


def is_service(identity: str) -> bool:
    return identity in _SERVICE_IDS


# -- OTP generation & verification ------------------------------------------

def generate_otp(email: str) -> str:
    """Generate a 6-digit OTP for the given email and store it."""
    code = "".join([str(secrets.randbelow(10)) for _ in range(OTP_LENGTH)])
    _OTP_STORE[email.lower().strip()] = {
        "code": code,
        "expires": time.time() + OTP_TTL,
        "attempts": 0,
    }
    return code


def verify_otp(email: str, code: str) -> bool:
    """Verify an OTP. Returns True on success, raises on failure."""
    email = email.lower().strip()
    entry = _OTP_STORE.get(email)
    if not entry:
        raise HTTPException(400, "No OTP was sent to this email. Please request a new code.")
    if entry["attempts"] >= OTP_MAX_ATTEMPTS:
        del _OTP_STORE[email]
        raise HTTPException(429, "Too many wrong attempts. Please request a new code.")
    if time.time() > entry["expires"]:
        del _OTP_STORE[email]
        raise HTTPException(400, "OTP has expired. Please request a new code.")
    if not hmac.compare_digest(entry["code"], code.strip()):
        entry["attempts"] += 1
        remaining = OTP_MAX_ATTEMPTS - entry["attempts"]
        raise HTTPException(
            401, f"Invalid code. {remaining} attempt{'s' if remaining != 1 else ''} remaining.")
    # success — clear the OTP
    del _OTP_STORE[email]
    return True


# -- email delivery ----------------------------------------------------------

def send_otp_email(email: str, code: str) -> None:
    """Send the OTP code via SMTP. Falls back to logging if SMTP is not
    configured (useful for local dev)."""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not smtp_host or not smtp_user:
        log.warning("SMTP not configured — OTP for %s: %s", email, code)
        return

    subject = f"Your DeckEngine verification code: {code}"
    html_body = f"""
    <div style="font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
                max-width: 480px; margin: 0 auto; padding: 40px 20px;">
      <h2 style="color: #2c3a47; font-family: Georgia, serif; margin: 0 0 8px;">
        Deck<span style="color: #c05621;">Engine</span>
      </h2>
      <p style="color: #6f6a61; font-size: 14px; margin: 0 0 32px;">
        Consulting-grade decks from a sentence.
      </p>
      <div style="background: #f4f2ec; border-radius: 12px; padding: 32px;
                  text-align: center; margin-bottom: 24px;">
        <p style="color: #6f6a61; font-size: 14px; margin: 0 0 12px;">
          Your verification code is
        </p>
        <div style="font-size: 36px; font-weight: 700; letter-spacing: 8px;
                    color: #2c3a47; font-family: monospace;">
          {code}
        </div>
      </div>
      <p style="color: #6f6a61; font-size: 13px;">
        This code expires in 5 minutes. If you didn't request this, ignore this email.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = email
    msg.attach(MIMEText(f"Your DeckEngine verification code: {code}\n\n"
                        "This code expires in 5 minutes.", "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log.info("OTP email sent to %s", email)
    except Exception as exc:
        log.error("Failed to send OTP email to %s: %s", email, exc)
        raise HTTPException(
            502, "Could not send verification email. Please try again.") from exc


# -- sessions ----------------------------------------------------------------

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

"""OTP login + sign-up + per-user deck quota: sessions, quota enforcement, ownership."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from deckengine.api import auth
from deckengine.api import main as api_main
from deckengine.api.main import app

SPEC = {
    "schema_version": 1, "theme": "consulting_navy",
    "meta": {"title": "q", "date": "13 Aug 2026", "footer_org": "DE"},
    "slides": [{"slide_type": "bullet_content", "title": "One",
                "bullets": [{"text": "a"}]}],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": {
        "u@example.com": {"quota": 1},
    }}), encoding="utf-8")
    monkeypatch.setattr(auth, "USERS_FILE", users)
    monkeypatch.setattr(auth, "SECRET_FILE", tmp_path / ".secret")
    monkeypatch.setattr(api_main, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(api_main, "_JOBS", {})
    monkeypatch.delenv("DECKENGINE_AUTH", raising=False)
    monkeypatch.delenv("DECKENGINE_API_KEY", raising=False)
    auth._OTP_STORE.clear()
    return TestClient(app)


def _otp_login(client, email="u@example.com"):
    """Send OTP, grab it from the in-memory store, verify it."""
    client.post("/auth/send-otp", json={"email": email})
    code = auth._OTP_STORE[email]["code"]
    return client.post("/auth/verify-otp", json={"email": email, "code": code})


def test_unauthenticated_is_blocked(client):
    assert client.get("/me").status_code == 401
    assert client.post("/generate",
                       json={"prompt": "x"}).status_code == 401
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login"
    assert "verification code" in client.get("/login").text.lower()


def test_wrong_otp_rejected(client):
    client.post("/auth/send-otp", json={"email": "u@example.com"})
    r = client.post("/auth/verify-otp",
                    json={"email": "u@example.com", "code": "000000"})
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


def test_expired_otp_rejected(client, monkeypatch):
    import time
    client.post("/auth/send-otp", json={"email": "u@example.com"})
    auth._OTP_STORE["u@example.com"]["expires"] = time.time() - 1
    r = client.post("/auth/verify-otp",
                    json={"email": "u@example.com", "code": "123456"})
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


def test_otp_login_me_logout_roundtrip(client):
    assert _otp_login(client).status_code == 200
    me = client.get("/me").json()
    assert me == {"email": "u@example.com", "quota": 1, "used": 0}
    client.post("/logout")
    assert client.get("/me").status_code == 401


def test_signup_creates_account_with_default_quota(client):
    r = _otp_login(client, "newuser@example.com")
    assert r.status_code == 200
    assert r.json()["is_new"] is True
    me = client.get("/me").json()
    assert me["email"] == "newuser@example.com"
    assert me["quota"] == auth.DEFAULT_QUOTA  # 2 by default
    assert me["used"] == 0


def test_quota_one_deck_then_403(client):
    _otp_login(client)
    r1 = client.post("/render", json={"spec": SPEC})
    assert r1.status_code == 200
    job_id = r1.json()["job_id"]
    assert client.get("/me").json()["used"] == 1
    r2 = client.post("/render", json={"spec": SPEC})
    assert r2.status_code == 403
    assert "limit" in r2.json()["detail"].lower()
    assert client.post("/generate",
                       json={"prompt": "another"}).status_code == 403
    # the finished deck stays fully accessible
    assert client.get(f"/jobs/{job_id}").json()["status"] == "done"
    assert client.get(f"/download/{job_id}").status_code == 200
    # own deck listed
    decks = client.get("/decks").json()
    assert [d["deck_id"] for d in decks] == [job_id]


def test_default_quota_is_two(client):
    """New sign-ups get 2 decks."""
    _otp_login(client, "fresh@example.com")
    me = client.get("/me").json()
    assert me["quota"] == 2
    r1 = client.post("/render", json={"spec": SPEC})
    assert r1.status_code == 200
    r2 = client.post("/render", json={"spec": SPEC})
    assert r2.status_code == 200
    assert client.get("/me").json()["used"] == 2
    r3 = client.post("/render", json={"spec": SPEC})
    assert r3.status_code == 403


def test_failed_deck_refunds_quota(client, tmp_path):
    _otp_login(client)
    bad = {**SPEC, "slides": []}  # fails DeckSpec min_length -> 422, no job
    assert client.post("/render", json={"spec": bad}).status_code == 422
    assert client.get("/me").json()["used"] == 0
    # simulate an errored job: does not count
    api_main._JOBS["deadbeef"] = {"status": "error", "owner": "u@example.com"}
    assert client.get("/me").json()["used"] == 0


def test_users_cannot_see_each_others_decks(client, tmp_path):
    users = json.loads(auth.USERS_FILE.read_text(encoding="utf-8"))
    users["users"]["v@example.com"] = {"quota": 1}
    auth.USERS_FILE.write_text(json.dumps(users), encoding="utf-8")
    _otp_login(client)
    job_id = client.post("/render", json={"spec": SPEC}).json()["job_id"]
    client.post("/logout")
    _otp_login(client, "v@example.com")
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get(f"/download/{job_id}").status_code == 404
    assert client.get("/decks").json() == []
    assert client.get("/me").json() == {"email": "v@example.com",
                                        "quota": 1, "used": 0}


def test_api_key_service_bypass(client, monkeypatch):
    monkeypatch.setenv("DECKENGINE_API_KEY", "sekret")
    h = {"X-API-Key": "sekret"}
    assert client.get("/me", headers=h).json()["email"] == "api"
    for _ in range(2):
        assert client.post("/render", json={"spec": SPEC},
                           headers=h).status_code == 200


def test_jobs_persist_across_restart(client):
    """A running job survives a process restart."""
    _otp_login(client)
    job_id = client.post("/render", json={"spec": SPEC}).json()["job_id"]
    api_main._JOBS.clear()
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "done" and job["owner"] == "u@example.com"
    assert client.get(f"/download/{job_id}").status_code == 200


def test_interrupted_job_marked_errored_and_refunds(client):
    _otp_login(client)
    jid = "feedbeefcafe"
    api_main._JOBS[jid] = {"status": "running", "owner": "u@example.com"}
    api_main._persist(jid)
    api_main._JOBS.clear()
    api_main._mark_interrupted_jobs()
    job = client.get(f"/jobs/{jid}").json()
    assert job["status"] == "error" and "restart" in job["error"]
    assert client.get("/me").json()["used"] == 0
    assert client.post("/render", json={"spec": SPEC}).status_code == 200


def test_done_meta_carries_slide_titles(client, monkeypatch):
    monkeypatch.setenv("DECKENGINE_PREVIEW", "none")
    _otp_login(client)
    job_id = client.post("/render", json={"spec": SPEC}).json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["slide_titles"] == ["One"]
    assert job["previews"] == 0


def test_seeded_owner_account_exists():
    """The committed data/users.json carries the real account."""
    real = json.loads((auth.REPO / "data" / "users.json")
                      .read_text(encoding="utf-8"))
    u = real["users"]["sd@skyquestt.com"]
    assert isinstance(u["quota"], int) and u["quota"] >= 1


def test_otp_max_attempts_lockout(client):
    """After OTP_MAX_ATTEMPTS wrong guesses the OTP is invalidated."""
    client.post("/auth/send-otp", json={"email": "u@example.com"})
    for _ in range(auth.OTP_MAX_ATTEMPTS):
        client.post("/auth/verify-otp",
                    json={"email": "u@example.com", "code": "000000"})
    r = client.post("/auth/verify-otp",
                    json={"email": "u@example.com", "code": "000000"})
    assert r.status_code in (400, 429)

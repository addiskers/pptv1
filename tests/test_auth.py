"""Login + per-user deck quota: sessions, quota enforcement, ownership."""
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
        "u@example.com": {"pw": auth.hash_password("pw123"), "quota": 1},
    }}), encoding="utf-8")
    monkeypatch.setattr(auth, "USERS_FILE", users)
    monkeypatch.setattr(auth, "SECRET_FILE", tmp_path / ".secret")
    monkeypatch.setattr(api_main, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(api_main, "_JOBS", {})
    monkeypatch.delenv("DECKENGINE_AUTH", raising=False)
    monkeypatch.delenv("DECKENGINE_API_KEY", raising=False)
    return TestClient(app)


def _login(client, email="u@example.com", pw="pw123"):
    return client.post("/login", json={"email": email, "password": pw})


def test_unauthenticated_is_blocked(client):
    assert client.get("/me").status_code == 401
    assert client.post("/generate",
                       json={"prompt": "x"}).status_code == 401
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login"
    assert "Sign in" in client.get("/login").text


def test_wrong_password_rejected(client):
    assert _login(client, pw="nope").status_code == 401


def test_login_me_logout_roundtrip(client):
    assert _login(client).status_code == 200
    me = client.get("/me").json()
    assert me == {"email": "u@example.com", "quota": 1, "used": 0}
    client.post("/logout")
    assert client.get("/me").status_code == 401


def test_quota_one_deck_then_403(client):
    _login(client)
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


def test_failed_deck_refunds_quota(client, tmp_path):
    _login(client)
    bad = {**SPEC, "slides": []}  # fails DeckSpec min_length -> 422, no job
    assert client.post("/render", json={"spec": bad}).status_code == 422
    assert client.get("/me").json()["used"] == 0
    # simulate an errored job: does not count
    api_main._JOBS["deadbeef"] = {"status": "error", "owner": "u@example.com"}
    assert client.get("/me").json()["used"] == 0


def test_users_cannot_see_each_others_decks(client, tmp_path):
    users = json.loads(auth.USERS_FILE.read_text(encoding="utf-8"))
    users["users"]["v@example.com"] = {"pw": auth.hash_password("pw456"),
                                       "quota": 1}
    auth.USERS_FILE.write_text(json.dumps(users), encoding="utf-8")
    _login(client)
    job_id = client.post("/render", json={"spec": SPEC}).json()["job_id"]
    client.post("/logout")
    _login(client, "v@example.com", "pw456")
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get(f"/download/{job_id}").status_code == 404
    assert client.get("/decks").json() == []
    # and v still has their own quota
    assert client.get("/me").json() == {"email": "v@example.com",
                                        "quota": 1, "used": 0}


def test_api_key_service_bypass(client, monkeypatch):
    monkeypatch.setenv("DECKENGINE_API_KEY", "sekret")
    h = {"X-API-Key": "sekret"}
    assert client.get("/me", headers=h).json()["email"] == "api"
    # service identity has no quota
    for _ in range(2):
        assert client.post("/render", json={"spec": SPEC},
                           headers=h).status_code == 200


def test_seeded_owner_account_exists():
    """The committed data/users.json carries the real account, hashed."""
    real = json.loads((auth.REPO / "data" / "users.json")
                      .read_text(encoding="utf-8"))
    u = real["users"]["sd@skyquestt.com"]
    assert u["quota"] == 1
    assert u["pw"].startswith("pbkdf2_sha256$")
    assert "hello" not in u["pw"]  # never plaintext

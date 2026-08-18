"""Dynamic intake questions: schema, prompt, API wiring, and the fold
into the LLM-facing prompt. Never a fixed form; never blocks compose."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from deckengine.api import auth
from deckengine.api import main as api_main
from deckengine.api.main import _fold_intake, app
from deckengine.llm.intake import IntakeQuestions, intake_prompt


def test_intake_questions_schema_round_trip():
    raw = {"questions": [
        {"id": "audience", "question": "Who reads this?",
         "kind": "choice", "options": ["Board", "Investors", "Ops"]},
        {"id": "tone", "question": "One recommendation or balanced options?",
         "kind": "short_text", "placeholder": "e.g. a single firm call"},
    ]}
    q = IntakeQuestions.model_validate(raw)
    assert len(q.questions) == 2
    assert q.questions[0].kind == "choice"
    assert q.questions[1].placeholder == "e.g. a single firm call"


def test_intake_questions_default_empty():
    assert IntakeQuestions.model_validate({}).questions == []


def test_intake_prompt_carries_brief_and_csv_flag():
    p = intake_prompt("Market entry for X in Indonesia", has_csv=False)
    assert "Market entry for X in Indonesia" in p
    assert "up to 5" in p
    p2 = intake_prompt("brief", has_csv=True)
    assert "do not ask about data" in p2.lower()


def test_fold_intake_empty_is_noop():
    assert _fold_intake("brief", None) == "brief"
    assert _fold_intake("brief", {}) == "brief"
    assert _fold_intake("brief", {"tone": "  "}) == "brief"  # blank-only ignored


def test_fold_intake_appends_readable_block():
    out = _fold_intake("brief", {"audience": "board", "tone": "  aggressive  "})
    assert out.startswith("brief")
    assert "STAKEHOLDER CONTEXT" in out
    assert "- audience: board" in out
    assert "- tone: aggressive" in out


# -- API wiring ---------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": {
        "u@example.com": {"pw": auth.hash_password("pw123"), "quota": 5},
    }}), encoding="utf-8")
    monkeypatch.setattr(auth, "USERS_FILE", users)
    monkeypatch.setattr(auth, "SECRET_FILE", tmp_path / ".secret")
    monkeypatch.setattr(api_main, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(api_main, "_JOBS", {})
    monkeypatch.delenv("DECKENGINE_AUTH", raising=False)
    monkeypatch.delenv("DECKENGINE_API_KEY", raising=False)
    c = TestClient(app)
    c.post("/login", json={"email": "u@example.com", "password": "pw123"})
    return c


def test_intake_endpoint_returns_questions(client, monkeypatch):
    from deckengine.llm import spec_generator as sg

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        assert name == "intake_questions"
        return {"questions": [
            {"id": "audience", "question": "Who reads this?",
             "kind": "short_text", "placeholder": "e.g. the board"}]}

    monkeypatch.setattr(sg, "_structured_call", fake)
    r = client.post("/intake", json={"prompt": "brief"})
    assert r.status_code == 200
    assert r.json()["questions"][0]["id"] == "audience"


def test_intake_endpoint_never_blocks_on_failure(client, monkeypatch):
    from deckengine.llm import spec_generator as sg

    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(sg, "_structured_call", boom)
    r = client.post("/intake", json={"prompt": "brief"})
    assert r.status_code == 200
    assert r.json() == {"questions": []}


def test_intake_endpoint_no_quota_charge(client, monkeypatch):
    from deckengine.llm import spec_generator as sg
    monkeypatch.setattr(sg, "_structured_call",
                        lambda *a, **k: {"questions": []})
    client.post("/intake", json={"prompt": "brief"})
    client.post("/intake", json={"prompt": "brief 2"})
    assert client.get("/me").json()["used"] == 0

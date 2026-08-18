"""The variant batch API: N decks from one brief, one quota unit, each
arguing via a distinct narrative flow. All LLM calls mocked."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from deckengine.api import auth
from deckengine.api import main as api_main
from deckengine.api.main import app
from deckengine.schema.slide_types import BulletContentSpec

_BULLET_BODY = [
    {"text": "Six corridors hold **58%** [[src:recon]] of national volume "
             "across every region sampled, with demand doubling since the "
             "price reset and dealer throughput running **2x** "
             "[[src:recon]] the non-corridor average; inventory clears in "
             "under nine days and waiting lists cover eight districts, so "
             "the thesis is an observed pattern, not a forecast."}]


def _bullets(title: str) -> dict:
    return BulletContentSpec.model_validate(
        {"slide_type": "bullet_content", "title": title,
         "bullets": _BULLET_BODY}).model_dump()


_FLOW_GOVERNING = {
    "options_decision": "Enter Indonesia via a distributor-led launch.",
    "pyramid": "The market is large enough and the entry lane is clear.",
    "benchmark": "Indonesia outperforms every peer market on the metrics that matter.",
}
_FLOW_TITLES = {
    "options_decision": "A distributor-led launch beats a JV on speed and capital",
    "pyramid": "The recommended answer is a staged Indonesia entry",
    "benchmark": "Indonesia leads the peer set on growth and channel depth",
}


def _fake_structured_call(flows):
    """Routes emit_outline calls to a per-flow governing_thought/title so
    each variant is genuinely distinguishable in the mock, and emits a
    minimal valid title/bullet_content pair for everything else."""
    def fake(name, schema, prompt, max_tokens=16000, **kw):
        if name == "deck_angles":
            return {"angles": [
                {"flow_id": f, "angle": f"Variant via {f}",
                 "emphasis_seed": f"lead with {f}"} for f in flows]}
        if name == "emit_outline":
            flow = next((f for f in flows if f"use '{f}'" in prompt), flows[0])
            return {"governing_thought": _FLOW_GOVERNING[flow],
                    "narrative_arc": flow,
                    "slides": [
                        {"slide_type": "title", "claim": "Cover"},
                        {"slide_type": "bullet_content",
                         "claim": _FLOW_TITLES[flow]}]}
        if name == "emit_title":
            return {"slide_type": "title", "title": "Cover"}
        return _bullets(_FLOW_TITLES.get(
            next((f for f in flows if f"use '{f}'" in prompt), flows[0]),
            "Fallback body"))
    return fake


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
    monkeypatch.setenv("DECKENGINE_DESIGNER", "0")     # keep the mock simple
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    c = TestClient(app)
    c.post("/login", json={"email": "u@example.com", "password": "pw123"})
    return c


def test_batch_creates_n_jobs_charges_one_quota_unit(client, monkeypatch):
    from deckengine.llm import spec_generator as sg
    flows = ["options_decision", "pyramid", "benchmark"]
    monkeypatch.setattr(sg, "_structured_call", _fake_structured_call(flows))
    r = client.post("/generate-batch",
                    json={"prompt": "Indonesia entry brief", "n": 3})
    assert r.status_code == 200
    data = r.json()
    assert len(data["job_ids"]) == 3
    # ONE quota unit for the whole batch, not 3
    assert client.get("/me").json()["used"] == 1


def test_batch_variants_get_distinct_flows_and_render(client, monkeypatch):
    from deckengine.llm import spec_generator as sg
    flows = ["options_decision", "pyramid", "benchmark"]
    monkeypatch.setattr(sg, "_structured_call", _fake_structured_call(flows))
    r = client.post("/generate-batch",
                    json={"prompt": "Indonesia entry brief", "n": 3})
    batch_id = r.json()["batch_id"]
    status = client.get(f"/batches/{batch_id}").json()
    assert status["done"] == status["total"] == 3
    got_flows = {v["flow_id"] for v in status["variants"]}
    assert got_flows == set(flows)          # every variant got a distinct flow
    assert all(v["status"] == "done" for v in status["variants"])
    for v in status["variants"]:
        dl = client.get(f"/download/{v['job_id']}")
        assert dl.status_code == 200


def test_batch_angle_count_mismatch_falls_back_deterministically(client, monkeypatch):
    from deckengine.llm import spec_generator as sg
    from deckengine.llm.narrative import FLOWS

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        if name == "deck_angles":
            return {"angles": [{"flow_id": "pyramid", "angle": "only one",
                                "emphasis_seed": ""}]}  # wrong count for n=3
        if name == "emit_outline":
            flow = next((f for f in FLOWS if f"use '{f}'" in prompt), "pyramid")
            return {"governing_thought": f"Answer via {flow}.",
                    "narrative_arc": flow,
                    "slides": [{"slide_type": "title", "claim": "Cover"},
                              {"slide_type": "bullet_content", "claim": "Body"}]}
        if name == "emit_title":
            return {"slide_type": "title", "title": "Cover"}
        return _bullets("Body")

    monkeypatch.setattr(sg, "_structured_call", fake)
    r = client.post("/generate-batch", json={"prompt": "brief", "n": 3})
    batch_id = r.json()["batch_id"]
    status = client.get(f"/batches/{batch_id}").json()
    flows_used = {v["flow_id"] for v in status["variants"]}
    assert len(flows_used) == 3              # fallback still gives 3 distinct flows
    assert status["done"] == 3


def test_batch_diversity_sweep_flags_similar_governing_thoughts(client, monkeypatch):
    from deckengine.llm import spec_generator as sg
    flows = ["options_decision", "pyramid"]

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        if name == "deck_angles":
            return {"angles": [{"flow_id": f, "angle": f, "emphasis_seed": ""}
                               for f in flows]}
        if name == "emit_outline":
            # both variants land the SAME governing thought despite different
            # flows — the diversity sweep must still catch it
            return {"governing_thought": "Enter Indonesia now via a distributor.",
                    "slides": [{"slide_type": "title", "claim": "Cover"},
                              {"slide_type": "bullet_content", "claim": "Body"}]}
        if name == "emit_title":
            return {"slide_type": "title", "title": "Cover"}
        return _bullets("Body")

    monkeypatch.setattr(sg, "_structured_call", fake)
    r = client.post("/generate-batch", json={"prompt": "brief", "n": 2})
    batch_id = r.json()["batch_id"]
    status = client.get(f"/batches/{batch_id}").json()
    assert all(v["similar_pairs"] for v in status["variants"])


def test_batch_one_bad_variant_does_not_sink_the_others(client, monkeypatch):
    from deckengine.llm import spec_generator as sg
    flows = ["options_decision", "pyramid", "benchmark"]

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        if name == "deck_angles":
            return {"angles": [{"flow_id": f, "angle": f, "emphasis_seed": ""}
                               for f in flows]}
        if name == "emit_outline":
            if "options_decision" in prompt:
                raise RuntimeError("simulated outline failure")
            flow = next((f for f in flows if f"use '{f}'" in prompt), "pyramid")
            return {"governing_thought": _FLOW_GOVERNING[flow],
                    "narrative_arc": flow,
                    "slides": [{"slide_type": "title", "claim": "Cover"},
                              {"slide_type": "bullet_content",
                               "claim": _FLOW_TITLES[flow]}]}
        if name == "emit_title":
            return {"slide_type": "title", "title": "Cover"}
        return _bullets("Body")

    monkeypatch.setattr(sg, "_structured_call", fake)
    r = client.post("/generate-batch", json={"prompt": "brief", "n": 3})
    batch_id = r.json()["batch_id"]
    status = client.get(f"/batches/{batch_id}").json()
    statuses = {v["status"] for v in status["variants"]}
    assert "error" in statuses and "done" in statuses
    assert status["done"] == 3   # errored + done both count as "finished"

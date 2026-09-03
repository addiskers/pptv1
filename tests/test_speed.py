"""T5.6 THE SPEED SESSION: combined repair pass, parallel waves with the
story fixed upfront, batch briefs, judge budget, post-sweeps, progress.
All LLM calls mocked."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from deckengine.llm import spec_generator as sg
from deckengine.llm.designer import silhouette
from deckengine.llm.story import Outline
from deckengine.schema.canvas import CanvasSlideSpec
from deckengine.schema.slide_types import BulletContentSpec, ChartSlideSpec

REPO = Path(__file__).resolve().parents[1]

CANVAS = json.loads(
    (REPO / "deckengine" / "llm" / "few_shots" / "canvas.json")
    .read_text(encoding="utf-8"))

BRIEF = {"message": "Drip wins on income.",
         "eye_lands_on": "the 3.4x multiple",
         "emphasis_entity": "Drip",
         "layout_concept": "hero stat left, chart right",
         "density": "balanced"}

_BULLET_BODY = [
    {"text": "Six corridors hold **58%** [[src:recon]] of national volume "
             "across every region we sampled, with demand doubling since "
             "the price reset and dealer throughput running **2x** "
             "[[src:recon]] the non-corridor average; inventory clears in "
             "under nine days and waiting lists cover eight districts, so "
             "the corridor thesis is an observed operating pattern rather "
             "than a forecast built on hope."},
    {"text": "Field teams logged the same pattern in every one of the six "
             "corridors: dealers reorder inside a week, financing approvals "
             "clear same-day, and returns stay under **1%** [[src:recon]] "
             "even during the monsoon disruption, which is the strongest "
             "signal available that the corridor structure itself, not a "
             "single hot market, is driving the volume."}]

TITLES = [
    "Six corridors hold **58%** [[src:recon]] of national sales volume",
    "Dealer margins widened to **9.1%** [[src:est]] after the price reset",
    "Service coverage reaches **312** [[src:official]] districts this year",
    "Fleet buyers renew at **86%** [[src:recon]], double the retail rate",
]


def _bullets(title: str) -> dict:
    return BulletContentSpec.model_validate(
        {"slide_type": "bullet_content", "title": title,
         "bullets": _BULLET_BODY}).model_dump()


def _clean_or_die(spec_dict: dict) -> dict:
    """Fixtures must pass every checker — a dirty fixture would add repair
    calls and make call-count/timing assertions flaky."""
    from deckengine.llm.emphasis import check_slide_emphasis
    from deckengine.llm.format_rules import check_slide_format
    from deckengine.llm.provenance import check_slide_markers
    from deckengine.llm.writing import check_slide_writing
    s = BulletContentSpec.model_validate(spec_dict)
    probs = (check_slide_writing(s) + check_slide_markers(s)
             + check_slide_format(s, None) + check_slide_emphasis(s))
    assert probs == [], f"fixture not clean: {probs}"
    return spec_dict


def _outline(claims: list[str], slide_type: str = "bullet_content") -> Outline:
    return Outline.model_validate({
        "governing_thought": "Go now.",
        "slides": [{"slide_type": slide_type, "claim": c} for c in claims]})


# -- ONE combined repair pass -------------------------------------------------

def test_three_failing_categories_one_repair_call(monkeypatch):
    src = "Source: company filings 2025 [[src:official]]"
    bad = ChartSlideSpec(
        title="Revenue may have tripled from 2019 to 2025",       # hedge
        chart={"kind": "native_chart", "chart_type": "line",       # 2 points
               "categories": ["2019", "2025"],
               "series": [{"name": "s", "values": [10, 30]}],
               "sort": "none", "highlight": None, "annotation": None},
    ).model_dump()                                                 # no source
    good = ChartSlideSpec(
        title="Revenue grew 3x from 2019 to 2025 across the portfolio",
        chart={"kind": "native_chart", "chart_type": "line",
               "categories": ["2019", "2021", "2023", "2025"],
               "series": [{"name": "s", "values": [10, 14, 22, 30]}],
               "sort": "none", "highlight": None, "annotation": None},
        footnote=src,
    ).model_dump()
    responses = [bad, good]
    prompts = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(sg, "_structured_call", fake)
    slide = sg.generate_slide("chart_slide", "claim", "prompt", None)
    # three categories failed, yet exactly ONE repair call fixed them all
    assert len(prompts) == 2
    repair = prompts[1]
    assert "[writing]" in repair
    assert "[format]" in repair
    assert "[provenance]" in repair
    assert "fix ALL of them at once" in repair
    assert len(slide.chart.categories) == 4


# -- parallel waves: story order preserved, real concurrency ------------------

def test_waves_run_parallel_and_preserve_claim_order(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    monkeypatch.setenv("DECKENGINE_DESIGNER", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    claims = [f"CLAIM-{i}: {t}" for i, t in enumerate(TITLES)]
    by_claim = {claims[i]: _clean_or_die(_bullets(TITLES[i]))
                for i in range(4)}
    lock = threading.Lock()
    active = [0]
    max_active = [0]

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        with lock:
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
        time.sleep(0.25)
        try:
            for c, spec in by_claim.items():
                # match the OWN slide's intent line, not the dedup-context
                # block (which lists every OTHER slide's claim too)
                if f"Slide intent: {c}" in prompt:
                    return dict(spec)
            raise AssertionError("no claim matched in prompt")
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(sg, "_structured_call", fake)
    t0 = time.monotonic()
    spec = sg.generate_deck_spec("prompt", outline=_outline(claims))
    elapsed = time.monotonic() - t0
    # concurrency actually happened (4 x 0.25s sequential would be >= 1.0s)
    assert max_active[0] >= 2
    assert elapsed < 0.85
    # THE STORY GATE: slides land in claim-chain order, not finish order
    # (marker mode appends a methodology slide after the 4 body slides)
    assert [s.title for s in spec.slides[:4]] == TITLES


# -- batch design-brief pre-pass ----------------------------------------------

def test_batch_briefs_one_call_no_per_slide_briefs(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    monkeypatch.setenv("DECKENGINE_DESIGNER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    variant = json.loads(json.dumps(CANVAS))
    variant["title"] = ("Solar pumps cut water draw **41%** [[src:recon]] "
                        "across the corridor belt")
    for el in variant["elements"]:
        el["x"] = min(0.6, el["x"] + 0.3)
        el["w"] = min(1 - el["x"], el["w"])
    names, prompts = [], []
    brief2 = dict(BRIEF, layout_concept="full-bleed band, table right")

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        names.append(name)
        prompts.append(prompt)
        if name == "design_briefs":
            return {"briefs": [dict(BRIEF), brief2]}
        if "ALPHA" in prompt:
            return json.loads(json.dumps(CANVAS))
        return json.loads(json.dumps(variant))

    monkeypatch.setattr(sg, "_structured_call", fake)
    spec = sg.generate_deck_spec("prompt", outline=_outline(
        ["ALPHA: drip pays back", "BETA: solar cuts draw"]))
    assert names.count("design_briefs") == 1     # ONE global brief call
    assert names.count("design_brief") == 0      # no per-slide fallbacks
    # both emissions carried their assigned brief
    emits = [p for n, p in zip(names, prompts) if n == "emit_canvas"]
    assert all("DESIGN BRIEF — follow it exactly" in p for p in emits)
    assert len(spec.slides) >= 2   # + auto methodology appendix in marker mode


def test_batch_brief_count_mismatch_falls_back(monkeypatch):
    calls = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        calls.append(name)
        return {"briefs": [dict(BRIEF)]}   # 1 brief for 2 slides

    monkeypatch.setattr(sg, "_structured_call", fake)
    got = sg._batch_briefs([("a", None, None), ("b", None, None)], None)
    assert got is None                      # per-slide fallback engages


# -- judge budget -------------------------------------------------------------

def test_judge_budget_semantics():
    b = sg.JudgeBudget(1)
    assert b.take() is True
    assert b.take() is False
    assert sg.JudgeBudget(0).take() is False


def test_exhausted_budget_skips_judge_deterministic_pick(monkeypatch,
                                                         tmp_path):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "2")
    variant = json.loads(json.dumps(CANVAS))
    # shift the right column one grid step left: changes the silhouette
    # signature while every element keeps its own w/h, so it stays a
    # valid (non-overlapping) design — CANVAS is packed edge-to-edge, so
    # clamped per-element resizing (the old approach) collided elements
    for el in variant["elements"]:
        if el["x"] >= 0.4:
            el["x"] = round(el["x"] - 0.083, 4)
    responses = [dict(BRIEF), json.loads(json.dumps(CANVAS)), variant]
    monkeypatch.setattr(
        sg, "_structured_call",
        lambda n, s, p, max_tokens=16000, **kw: (
            responses.pop(0) if responses else json.loads(
                json.dumps(variant))))
    fake_pptx = tmp_path / "c.pptx"
    fake_pptx.write_bytes(b"x")
    monkeypatch.setattr(
        sg, "_render_candidate",
        lambda slide, theme, wd, tag: {"defects": 0, "fill": 0.9,
                                       "pptx": fake_pptx})
    monkeypatch.setattr(sg, "_export_png", lambda p: fake_pptx)
    monkeypatch.setattr(sg, "_record_win", lambda a, s: None)
    from deckengine.llm import judge
    judged = []
    monkeypatch.setattr(judge, "pairwise_judge",
                        lambda a, b, c: (judged.append(1), ("A", "r"))[1])
    # budget spent -> deterministic pick, no judge call
    slide = sg.generate_slide_best("canvas", "claim", "ctx", None,
                                   judge_budget=sg.JudgeBudget(0))
    assert judged == [] and slide.slide_type == "canvas"
    # budget available -> the tie goes to the judge
    responses[:] = [dict(BRIEF), json.loads(json.dumps(CANVAS)), variant]
    sg.generate_slide_best("canvas", "claim", "ctx", None,
                           judge_budget=sg.JudgeBudget(6))
    assert judged == [1]


# -- fast mode ----------------------------------------------------------------

def test_fast_quality_single_candidate_no_judge(monkeypatch):
    monkeypatch.delenv("DECKENGINE_CANDIDATES", raising=False)  # default 2
    monkeypatch.setenv("DECKENGINE_DESIGNER", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    claims = [f"CLAIM-{i}: {t}" for i, t in enumerate(TITLES[:2])]
    by_claim = {claims[i]: _clean_or_die(_bullets(TITLES[i]))
                for i in range(2)}
    prompts = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        prompts.append(prompt)
        for c, spec in by_claim.items():
            if f"Slide intent: {c}" in prompt:
                return dict(spec)
        raise AssertionError("no claim matched")

    monkeypatch.setattr(sg, "_structured_call", fake)
    stages = []
    spec = sg.generate_deck_spec(
        "prompt", outline=_outline(claims), quality="fast",
        progress_cb=lambda d, t, s: stages.append((d, t, s)))
    assert len(spec.slides) >= 2   # + auto methodology appendix in marker mode
    # fast = ONE candidate: no variant nudge ever issued
    assert all("Variant instruction" not in p for p in prompts)
    assert len(prompts) == 2
    # progress ticked through the stages and reached done == total
    assert ("outline" in [s for _, _, s in stages])
    assert (2, 2, "designing") in stages
    assert any(s == "polishing" for _, _, s in stages)


# -- deterministic post-sweeps ------------------------------------------------

def test_dupe_pairs_detector():
    a = "Indonesia leads the region with **214M** [[src:recon]] consumers"
    b = "Indonesia leads with 214M consumers across the region"
    c = "Dealer margins widened to 9.1% after the price reset"
    assert sg._dupe_pairs([a, b, c]) == [(0, 1)]
    assert sg._dupe_pairs([a, c]) == []
    # near-identical wording without a shared figure also counts
    d = "Vietnam offers the strongest entry corridor for premium brands"
    e = "Vietnam offers the strongest entry corridor for premium products"
    assert sg._dupe_pairs([d, e]) == [(0, 1)]


def test_sweeps_regen_adjacent_same_silhouette(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    monkeypatch.setenv("DECKENGINE_DESIGNER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    names = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        names.append(name)
        if name == "design_briefs":
            return {"briefs": [dict(BRIEF), dict(BRIEF)]}
        if name == "design_brief":
            return dict(BRIEF)
        return json.loads(json.dumps(CANVAS))   # every design identical

    monkeypatch.setattr(sg, "_structured_call", fake)
    spec = sg.generate_deck_spec("prompt", outline=_outline(
        ["ALPHA: drip pays back", "BETA: solar cuts draw"]))
    # both slides landed identical -> the sweeps attempted targeted regens
    n_emits = names.count("emit_canvas")
    assert n_emits >= 3            # 2 wave emissions + at least one sweep regen
    body = spec.slides[:2]         # + auto methodology appendix in marker mode
    assert len(body) == 2          # sweeps polish, never drop slides
    assert all(s.slide_type == "canvas" for s in body)


def test_sweep_keeps_original_when_regen_no_better(monkeypatch):
    """A silhouette-sweep regen that lands the SAME silhouette is discarded
    — the sweep only ever improves the deck."""
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    monkeypatch.setenv("DECKENGINE_DESIGNER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        if name == "design_briefs":
            return {"briefs": [dict(BRIEF), dict(BRIEF)]}
        if name == "design_brief":
            return dict(BRIEF)
        return json.loads(json.dumps(CANVAS))

    monkeypatch.setattr(sg, "_structured_call", fake)
    spec = sg.generate_deck_spec("prompt", outline=_outline(
        ["ALPHA: drip pays back", "BETA: solar cuts draw"]))
    sils = [silhouette(CanvasSlideSpec.model_validate(s.model_dump()))
            for s in spec.slides[:2]]   # + auto methodology appendix
    assert sils[0] == sils[1]      # regen couldn't differ -> originals kept

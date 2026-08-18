"""Render-truth repair: overlap/overflow measured on the ACTUAL render
becomes one repair call — fast mode's first render feedback. Plus the
crash class it closes: invented color roles coerce/fall back, never die."""
from __future__ import annotations

import json
from pathlib import Path

from deckengine.core.theme import load_theme
from deckengine.llm import spec_generator as sg
from deckengine.schema.canvas import CanvasSlideSpec

REPO = Path(__file__).resolve().parents[1]

CLEAN = json.loads(
    (REPO / "eval" / "goldens" / "canvas_hero.json")
    .read_text(encoding="utf-8"))["slides"][0]

# spec-valid but renders dirty: two same-z text blocks painted over each
# other (the audit catches it on the rendered output)
DIRTY = {
    "slide_type": "canvas", "title": "Clip test",
    "elements": [
        {"x": 0.05, "y": 0.2, "w": 0.5, "h": 0.3, "z": 1,
         "content": {"kind": "canvas_text",
                     "text": "first block of body text that is long "
                             "enough to matter for the overlap"}},
        {"x": 0.05, "y": 0.25, "w": 0.5, "h": 0.3, "z": 1,
         "content": {"kind": "canvas_text",
                     "text": "second block painted over the first one"}},
    ]}


def _slide(d):
    return CanvasSlideSpec.model_validate(d)


def test_render_problems_fire_on_dirty_and_not_on_clean():
    assert sg._render_problems(_slide(DIRTY), "consulting_navy")
    assert sg._render_problems(_slide(CLEAN), "consulting_navy") == []


def test_dirty_slide_repaired_with_one_call(monkeypatch):
    monkeypatch.setenv("DECKENGINE_RENDER_REPAIR", "1")
    calls = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        calls.append((name, prompt))
        return json.loads(json.dumps(CLEAN))

    monkeypatch.setattr(sg, "_structured_call", fake)
    out = sg._maybe_render_repair(_slide(DIRTY), "claim", "prompt", None,
                                  "consulting_navy")
    assert len(calls) == 1
    name, prompt = calls[0]
    assert name == "emit_canvas"
    assert "MEASURED DEFECTS" in prompt and "[render]" in prompt
    assert "CURRENT SPEC" in prompt
    # the repair rendered cleaner -> accepted
    assert sg._render_problems(out, "consulting_navy") == []


def test_repair_rejected_when_no_better(monkeypatch):
    monkeypatch.setenv("DECKENGINE_RENDER_REPAIR", "1")
    monkeypatch.setattr(
        sg, "_structured_call",
        lambda n, s, p, max_tokens=16000, **kw: json.loads(
            json.dumps(DIRTY)))   # the "repair" is just as dirty
    slide = _slide(DIRTY)
    out = sg._maybe_render_repair(slide, "claim", "prompt", None,
                                  "consulting_navy")
    assert out is slide            # original kept


def test_clean_slide_skips_repair_entirely(monkeypatch):
    monkeypatch.setenv("DECKENGINE_RENDER_REPAIR", "1")
    def boom(*a, **k):
        raise AssertionError("no repair call for a clean render")

    monkeypatch.setattr(sg, "_structured_call", boom)
    slide = _slide(CLEAN)
    assert sg._maybe_render_repair(slide, "claim", "prompt", None,
                                   "consulting_navy") is slide


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("DECKENGINE_RENDER_REPAIR", "0")

    def boom(*a, **k):
        raise AssertionError("repair disabled by env")

    monkeypatch.setattr(sg, "_structured_call", boom)
    slide = _slide(DIRTY)
    assert sg._maybe_render_repair(slide, "claim", "prompt", None,
                                   "consulting_navy") is slide


def test_generate_slide_best_runs_render_repair(monkeypatch):
    seen = []
    monkeypatch.setattr(sg, "_pick_slide_best",
                        lambda *a, **k: _slide(CLEAN))
    monkeypatch.setattr(
        sg, "_maybe_render_repair",
        lambda slide, claim, prompt, facts, theme: seen.append(theme) or slide)
    sg.generate_slide_best("canvas", "c", "p", None, theme="teal_coral")
    assert seen == ["teal_coral"]


# -- the crash class this closes ----------------------------------------------

def test_unknown_color_role_falls_back_not_raises():
    t = load_theme("consulting_navy")
    assert t.color("safe") == t.color("ink")   # the exact live crash


def test_invented_roles_coerce_at_validation():
    s = CanvasSlideSpec.model_validate({
        "slide_type": "canvas", "title": "T", "bg_fill_role": "nonsense",
        "elements": [
            {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2,
             "content": {"kind": "canvas_shape", "fill_role": "safe",
                         "label": "x", "label_color_role": "made_up"}},
            {"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.2,
             "content": {"kind": "canvas_text", "text": "hi",
                         "color_role": "bogus"}},
        ]})
    assert s.bg_fill_role is None                       # bad bg -> no wash
    assert s.elements[0].content.fill_role == "surface"
    assert s.elements[0].content.label_color_role == "ink"
    assert s.elements[1].content.color_role == "ink"
    # legal roles pass through untouched
    s2 = CanvasSlideSpec.model_validate({
        "slide_type": "canvas", "title": "T",
        "elements": [
            {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2,
             "content": {"kind": "canvas_shape",
                         "fill_role": "primary_dark"}},
            {"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.2,
             "content": {"kind": "canvas_text", "text": "hi",
                         "color_role": "inverse_ink"}},
        ]})
    assert s2.elements[0].content.fill_role == "primary_dark"
    assert s2.elements[1].content.color_role == "inverse_ink"


def test_component_roles_coerce_too():
    from deckengine.schema.components import HighlightBoxSpec
    h = HighlightBoxSpec.model_validate(
        {"kind": "highlight_box", "title": "t", "body": "b",
         "fill_role": "safe"})
    assert h.fill_role == "surface"

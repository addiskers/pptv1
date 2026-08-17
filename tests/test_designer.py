"""The designer chain: briefs, silhouette memory, canvas-first generation
with archetype fallback (all LLM calls mocked)."""
from __future__ import annotations

import json
from pathlib import Path

from deckengine.llm import spec_generator as sg
from deckengine.llm.designer import (DesignBrief, describe_silhouette,
                                     silhouette)
from deckengine.schema.canvas import CanvasSlideSpec
from deckengine.schema.slide_types import BulletContentSpec

REPO = Path(__file__).resolve().parents[1]

CANVAS = json.loads(
    (REPO / "deckengine" / "llm" / "few_shots" / "canvas.json")
    .read_text(encoding="utf-8"))

BRIEF = {"message": "Drip wins on income.",
         "eye_lands_on": "the 3.4x multiple",
         "emphasis_entity": "Drip",
         "layout_concept": "hero stat left, chart right",
         "density": "balanced"}

BULLETS = BulletContentSpec(
    title="Fallback slide carries the claim at 58% [[src:recon]] share",
    bullets=[{"text": "Six corridors hold **58%** [[src:recon]] of national "
                      "volume across every region we sampled, with demand "
                      "doubling since the price reset and dealer throughput "
                      "running **2x** the non-corridor average; inventory "
                      "clears in under nine days and waiting lists cover "
                      "eight districts, so the corridor thesis is not a "
                      "forecast but an observed operating pattern."}],
).model_dump()


# -- silhouettes -------------------------------------------------------------

def test_silhouette_distinguishes_layouts():
    a = CanvasSlideSpec.model_validate(CANVAS)
    moved = json.loads(json.dumps(CANVAS))
    for el in moved["elements"]:
        el["x"] = min(0.6, el["x"] + 0.3)
        el["w"] = min(1 - el["x"], el["w"])
    b = CanvasSlideSpec.model_validate(moved)
    assert silhouette(a) != silhouette(b)
    assert silhouette(a) == silhouette(CanvasSlideSpec.model_validate(CANVAS))


def test_silhouette_archetype_is_its_type():
    s = BulletContentSpec.model_validate(BULLETS)
    assert silhouette(s) == "bullet_content"
    assert describe_silhouette("bullet_content") == "bullet_content"
    assert "text" in describe_silhouette(
        silhouette(CanvasSlideSpec.model_validate(CANVAS)))


# -- brief threading ---------------------------------------------------------

def test_canvas_generation_makes_brief_then_design(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    calls = []

    def fake(name, schema, prompt, max_tokens=16000):
        calls.append((name, prompt))
        if name == "design_brief":
            return dict(BRIEF)
        return json.loads(json.dumps(CANVAS))

    monkeypatch.setattr(sg, "_structured_call", fake)
    slide = sg.generate_slide_best("canvas", "Drip returns 3.4x", "ctx",
                                   None, visual_concept="hero split")
    assert slide.slide_type == "canvas"
    assert calls[0][0] == "design_brief"
    assert "hero split" in calls[0][1]          # outline concept reaches brief
    emit = calls[1][1]
    assert "DESIGN BRIEF" in emit and "3.4x" in emit
    assert "CANVAS DESIGN RULES" in emit


def test_second_candidate_briefed_to_differ(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "2")
    prompts = []
    variant = json.loads(json.dumps(CANVAS))
    variant["elements"] = variant["elements"][:4]
    responses = [dict(BRIEF), json.loads(json.dumps(CANVAS)), variant]

    def fake(name, schema, prompt, max_tokens=16000):
        prompts.append((name, prompt))
        return responses.pop(0)

    monkeypatch.setattr(sg, "_structured_call", fake)
    monkeypatch.setattr(
        sg, "_render_candidate",
        lambda slide, theme, wd, tag: {"defects": 0 if tag == "cand0" else 3,
                                       "fill": 0.9, "pptx": None})
    sg.generate_slide_best("canvas", "claim", "ctx", None)
    emits = [p for n, p in prompts if n != "design_brief"]
    assert "follow it exactly" in emits[0]
    assert "DIFFERENT layout concept" in emits[1]


def test_failed_brief_never_blocks(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")

    def fake(name, schema, prompt, max_tokens=16000):
        if name == "design_brief":
            raise RuntimeError("brief exploded")
        return json.loads(json.dumps(CANVAS))

    monkeypatch.setattr(sg, "_structured_call", fake)
    slide = sg.generate_slide_best("canvas", "claim", "ctx", None)
    assert slide.slide_type == "canvas"


# -- silhouette scoring ------------------------------------------------------

def test_repeat_silhouette_loses_tie(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "2")
    same = json.loads(json.dumps(CANVAS))
    different = json.loads(json.dumps(CANVAS))
    for el in different["elements"]:
        el["y"] = min(0.75, el["y"] + 0.25)
        el["h"] = min(1 - el["y"], el["h"])
    responses = [dict(BRIEF), same, different]
    monkeypatch.setattr(
        sg, "_structured_call",
        lambda n, s, p, max_tokens=16000: (
            responses.pop(0) if responses else json.loads(
                json.dumps(different))))  # repairs re-emit the variant
    monkeypatch.setattr(
        sg, "_render_candidate",
        lambda slide, theme, wd, tag: {"defects": 0, "fill": 0.9,
                                       "pptx": None})
    prev = silhouette(CanvasSlideSpec.model_validate(CANVAS))
    slide = sg.generate_slide_best("canvas", "claim", "ctx", None,
                                   recent_silhouettes=[prev])
    # the candidate matching the previous slide's silhouette must lose
    assert silhouette(slide) != prev


# -- designer-first deck loop ------------------------------------------------

def test_deck_loop_designs_canvas_with_archetype_fallback(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    monkeypatch.setenv("DECKENGINE_DESIGNER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # provider() log line
    from deckengine.llm.story import Outline
    outline = Outline.model_validate({
        "governing_thought": "Go.",
        "slides": [{"slide_type": "title", "claim": "Cover"},
                   {"slide_type": "bullet_content",
                    "claim": "Corridors hold the volume",
                    "visual_concept": "hero split"}]})

    def fake(name, schema, prompt, max_tokens=16000):
        if name == "design_brief":
            return dict(BRIEF)
        if name == "emit_canvas":
            raise RuntimeError("canvas keeps failing")   # force fallback
        if name == "emit_title":
            return {"slide_type": "title", "title": "Cover"}
        return json.loads(json.dumps(BULLETS))

    monkeypatch.setattr(sg, "_structured_call", fake)
    spec = sg.generate_deck_spec("prompt", outline=outline)
    types = [s.slide_type for s in spec.slides]
    assert "bullet_content" in types            # fallback delivered the slide


def test_designer_off_keeps_archetypes(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    monkeypatch.setenv("DECKENGINE_DESIGNER", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # provider() log line
    from deckengine.llm.story import Outline
    outline = Outline.model_validate({
        "governing_thought": "Go.",
        "slides": [{"slide_type": "title", "claim": "Cover"},
                   {"slide_type": "bullet_content", "claim": "C"}]})
    names = []

    def fake(name, schema, prompt, max_tokens=16000):
        names.append(name)
        if name == "emit_title":
            return {"slide_type": "title", "title": "Cover"}
        return json.loads(json.dumps(BULLETS))

    monkeypatch.setattr(sg, "_structured_call", fake)
    sg.generate_deck_spec("prompt", outline=outline)
    assert all(n != "design_brief" for n in names)
    assert any(n == "emit_bullet_content" for n in names)

"""The variant batch's diversity pre-pass: distinct flow assignment, its
deterministic fallback, and generate_outline's forced_flow override."""
from __future__ import annotations

import json

from deckengine.llm import spec_generator as sg
from deckengine.llm.narrative import FLOWS
from deckengine.llm.variants import (DeckAngles, angle_prompt,
                                     fallback_angles)


def test_fallback_angles_distinct_flows():
    angles = fallback_angles(5)
    assert len(angles) == 5
    assert len({a.flow_id for a in angles}) == 5
    assert all(a.flow_id in FLOWS for a in angles)


def test_fallback_angles_wraps_past_flow_count():
    n = len(FLOWS) + 3
    angles = fallback_angles(n)
    assert len(angles) == n
    assert all(a.flow_id in FLOWS for a in angles)


def test_angle_prompt_carries_brief_and_flow_menu():
    p = angle_prompt("Market entry brief", 5)
    assert "Market entry brief" in p
    assert "5" in p
    assert all(fid in p for fid in list(FLOWS)[:3])


def test_deck_angles_schema_round_trip():
    raw = {"angles": [
        {"flow_id": "options_decision", "angle": "Frame as a go/no-go choice.",
         "emphasis_seed": "capital efficiency"},
        {"flow_id": "pyramid", "angle": "Lead with the answer.",
         "emphasis_seed": "speed to market"},
    ]}
    out = DeckAngles.model_validate(raw)
    assert len(out.angles) == 2
    assert out.angles[0].flow_id == "options_decision"


# -- generate_outline forced_flow ---------------------------------------------

_GOOD_OUTLINE = {
    "governing_thought": "Enter Indonesia via a distributor-led launch.",
    "slides": [
        {"slide_type": "title", "claim": "Indonesia entry"},
        {"slide_type": "chart_slide", "claim": "The market clears the size bar"},
    ]}


def test_forced_flow_overrides_prompt_and_narrative_arc(monkeypatch):
    prompts = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        prompts.append(prompt)
        # the model "disobeys" and picks a different arc — code must win anyway
        return {**_GOOD_OUTLINE, "narrative_arc": "scqa"}

    monkeypatch.setattr(sg, "_structured_call", fake)
    outline = sg.generate_outline("brief", None, forced_flow="options_decision",
                                  angle_hint="lead with capital efficiency")
    assert "FIXED" in prompts[0]
    assert "which option should we choose?" in prompts[0]
    assert "lead with capital efficiency" in prompts[0]
    assert "FIRST choose the deck FLOW" not in prompts[0]
    # deterministic override survives both the draft AND the review pass
    assert outline.narrative_arc == "options_decision"


def test_unknown_forced_flow_falls_back_to_normal_menu(monkeypatch):
    prompts = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        prompts.append(prompt)
        return dict(_GOOD_OUTLINE)

    monkeypatch.setattr(sg, "_structured_call", fake)
    sg.generate_outline("brief", None, forced_flow="not_a_real_flow")
    assert "FIRST choose the deck FLOW" in prompts[0]


def test_no_forced_flow_keeps_original_behavior(monkeypatch):
    prompts = []

    def fake(name, schema, prompt, max_tokens=16000, **kw):
        prompts.append(prompt)
        return dict(_GOOD_OUTLINE)

    monkeypatch.setattr(sg, "_structured_call", fake)
    outline = sg.generate_outline("brief", None)
    assert "FIRST choose the deck FLOW" in prompts[0]
    assert outline.narrative_arc is None

"""The story brain (flows + flow critic) and the chart canon."""
from __future__ import annotations

import re

from deckengine.llm.canon import CANON, census_vocabulary, gaps
from deckengine.llm.narrative import (FLOWS, SLIDE_PRINCIPLES,
                                      check_outline_flow, flow_menu)
from deckengine.llm.story import Outline


def _outline(arc, claims, sections=None):
    sections = sections or [None] * len(claims)
    return Outline.model_validate({
        "governing_thought": "Do the thing.",
        "narrative_arc": arc,
        "slides": [{"slide_type": "canvas", "claim": c, "section": s}
                   for c, s in zip(claims, sections)]})


# -- registry sanity ---------------------------------------------------------

def test_nineteen_flows_with_valid_grammars():
    assert len(FLOWS) == 19
    for f in FLOWS.values():
        assert f.meta_question.endswith("?") or "." in f.meta_question
        assert f.beats, f.id
        for b in f.beats:
            re.compile(b.signal)          # every signal is a valid regex
        if f.closing:
            re.compile(f.closing)


def test_flow_menu_lists_all():
    menu = flow_menu()
    for fid in FLOWS:
        assert fid in menu


def test_principles_block_is_prompt_sized():
    assert 300 < len(SLIDE_PRINCIPLES) < 900
    assert "ONE idea per slide" in SLIDE_PRINCIPLES


# -- the flow critic ---------------------------------------------------------

def test_options_deck_missing_recommendation_flagged():
    o = _outline("options_decision", [
        "Three entry options are on the table: build, buy, partner",
        "The evaluation criteria weigh speed, capital and control",
        "Market data favors rapid moves",
    ])
    problems = check_outline_flow(o)
    assert any("recommendation" in p for p in problems)


def test_complete_options_deck_passes():
    o = _outline("options_decision", [
        "Three entry options are on the table: build, buy, partner",
        "Against the evaluation criteria, partnering scores highest",
        "We recommend the partnership route as the next step decision",
    ])
    assert check_outline_flow(o) == []


def test_data_slide_ending_flagged():
    o = _outline("scqa", [
        "The market today is stable and consolidated",
        "But new entrants threaten the core business",
        "We should move now — the recommended response",
        "Appendix: regional volumes by quarter",
    ])
    problems = check_outline_flow(o)
    assert any("CLOSE" in p or "end on a data slide" in p for p in problems)


def test_unknown_or_missing_arc_skips():
    o = _outline("interpretive_dance", ["A claim", "Another claim"])
    assert check_outline_flow(o) == []
    o2 = _outline(None, ["A claim", "Another claim"])
    assert check_outline_flow(o2) == []


def test_arc_normalized():
    o = _outline("Options Decision", ["Option build or buy",
                                      "We recommend buy as the decision"])
    assert o.narrative_arc == "options_decision"


# -- the canon ---------------------------------------------------------------

def test_canon_covers_the_families():
    fams = {f.family for f in CANON.values()}
    assert fams >= {"comparison", "composition", "trend", "distribution",
                    "relationship", "flow", "deviation", "multi_criteria",
                    "diagram", "number"}
    assert len(CANON) >= 55


def test_canon_gaps_include_user_named_forms():
    g = set(gaps())
    # still-open gaps (mekko/radar barely appear in the census; backlog)
    assert {"mekko", "radar", "sankey", "gauge"} <= g
    # graduated to primitives: pyramid+gantt (T5), the census wave, then
    # wave 3 (cycle/tree/onion — the SmartArt-class drawn forms)
    for form in ("pyramid", "gantt", "venn", "bubble", "scatter",
                 "quadrant_scatter", "staircase", "hub_spoke",
                 "combo_line_column", "flywheel", "issue_tree",
                 "driver_tree", "onion"):
        assert CANON[form].status == "primitive", form


def test_non_gap_entries_name_engine_recipes():
    for f in CANON.values():
        if f.status == "gap":
            assert f.engine is None
        else:
            assert f.engine, f.id


def test_census_vocabulary_superset():
    v = census_vocabulary()
    assert "mekko" in v and "photo_hero" in v and "other" in v

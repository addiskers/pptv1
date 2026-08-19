"""Two-stage framework selection: labelled cases, the evidence gate, the
honest no-data path, tie handling, deck caps — and the COLLAPSE GUARD
(no framework may dominate the shortlists; the guard that would have
caught the everything-is-BCG failure months earlier)."""
from __future__ import annotations

from collections import Counter

from deckengine.llm.facts import FactTable
from deckengine.llm.frameworks import (FRAMEWORKS, assign_frameworks,
                                       check_framework_slide,
                                       check_framework_verdicts,
                                       detect_signals, shortlist_for,
                                       ties_prompt)
from deckengine.llm.story import Outline, OutlineSlide


def _outline(sections: list[tuple[str, str, list[str]]]) -> Outline:
    """sections: (tag, decision_type, claims). Builds a valid outline."""
    slides = [OutlineSlide(slide_type="title", claim="The answer up front")]
    for tag, dt, claims in sections:
        for c in claims:
            slides.append(OutlineSlide(slide_type="chart_slide", claim=c,
                                       section=tag, decision_type=dt))
    return Outline(governing_thought="We should act now because the "
                                     "evidence supports it.",
                   slides=slides)


PORTFOLIO_CSV = """unit,revenue,market share,growth
Alpha,100,32,12
Beta,80,21,4
Gamma,60,12,18
"""

RICH_PORTFOLIO_CSV = """unit,revenue,market share,growth,brand score,service score
Alpha,100,32,12,8,7
Beta,80,21,4,6,5
Gamma,60,12,18,7,8
Delta,40,9,22,5,6
Epsilon,30,6,25,4,7
Zeta,20,4,30,3,5
"""


# -- labelled selection cases -------------------------------------------------

def test_portfolio_with_share_growth_gets_bcg():
    facts = FactTable.from_csv(PORTFOLIO_CSV)
    sig = detect_signals("allocate capital across our three units", facts)
    short = shortlist_for("portfolio_allocation", sig)
    assert [f.id for f in short] == ["bcg_matrix"]


def test_rich_portfolio_gets_nine_box_not_bcg():
    facts = FactTable.from_csv(RICH_PORTFOLIO_CSV)
    sig = detect_signals("score six units on weighted criteria", facts)
    assert {"many_units", "multi_criteria"} <= sig
    short = shortlist_for("portfolio_allocation", sig)
    assert [f.id for f in short] == ["ge_mckinsey_nine_box"]


def test_portfolio_without_data_gets_nothing():
    # THE case that motivated the redesign: the old selector invented
    # share/growth numbers; the new one declines — no data, no BCG
    sig = detect_signals("which of our business lines should we back?",
                         None)
    assert shortlist_for("portfolio_allocation", sig) == []


def test_qualitative_decisions_map_one_to_one():
    sig = detect_signals("should we enter the India laptop market?", None)
    expected = {"market_attractiveness": "porters_five_forces",
                "growth_path": "ansoff_matrix",
                "org_execution": "mckinsey_7s",
                "cost_structure": "value_chain",
                "macro_risk": "pestle",
                "problem_structuring": "issue_tree",
                "category_creation": "blue_ocean_errc",
                "stocktake": "swot"}
    for dt, fid in expected.items():
        assert [f.id for f in shortlist_for(dt, sig)] == [fid], dt


def test_positioning_surfaces_both_candidates():
    sig = detect_signals("competitive intelligence review", None)
    short = shortlist_for("positioning", sig)
    assert {f.id for f in short} == {"three_cs",
                                     "porters_generic_strategies"}


def test_unknown_decision_type_gets_nothing():
    assert shortlist_for("vibes", set()) == []
    assert shortlist_for("none", set()) == []


# -- signals without a dataset ------------------------------------------------

def test_many_units_never_granted_without_dataset():
    sig = detect_signals(
        "we have market share and growth and scoring criteria for twelve "
        "units", None)
    assert "many_units" not in sig  # a nine-box can't be earned on vibes
    assert {"per_unit_share", "per_unit_growth", "multi_criteria"} <= sig


# -- assignment over an outline -----------------------------------------------

def test_assign_marks_anchor_and_respects_none():
    o = _outline([
        ("WHY ENTER", "market_attractiveness",
         ["The market grew fast", "The industry is attractive to enter"]),
        ("BACKGROUND", "none", ["Context slide claim goes here"]),
    ])
    picked = assign_frameworks(o, "should we enter?", None)
    assert picked == {"WHY ENTER": "porters_five_forces"}
    # anchor = the claim already matching the verdict signal (slide 3)
    assert o.slides[2].framework == "porters_five_forces"
    assert o.slides[1].framework is None
    assert o.slides[3].framework is None


def test_assign_clears_model_hallucinated_frameworks():
    o = _outline([("BACKGROUND", "none", ["Context only, no decision"])])
    o.slides[1].framework = "bcg_matrix"  # model wrote it; engine clears
    assert assign_frameworks(o, "an informational update", None) == {}
    assert o.slides[1].framework is None


def test_deck_cap_two_evidence_backed_first():
    facts = FactTable.from_csv(PORTFOLIO_CSV)
    o = _outline([
        ("MACRO", "macro_risk", ["Regulation could reshape the market"]),
        ("ENTRY", "market_attractiveness", ["The industry is attractive"]),
        ("PORTFOLIO", "portfolio_allocation",
         ["We should divest the weakest unit"]),
    ])
    picked = assign_frameworks(o, "market share and growth by unit", facts)
    assert len(picked) == 2
    # the evidence-backed BCG outranks the qualitative ones; earliest
    # section breaks the remaining tie
    assert picked["PORTFOLIO"] == "bcg_matrix"
    assert "MACRO" in picked and "ENTRY" not in picked


def test_tie_resolved_by_chooser_and_invalid_pick_means_none():
    o = _outline([("POSITIONING", "positioning",
                   ["We win the premium niche on differentiation"])])
    picked = assign_frameworks(
        o, "positioning strategy", None,
        choose=lambda ties: {t[0]: "porters_generic_strategies"
                             for t in ties})
    assert picked == {"POSITIONING": "porters_generic_strategies"}

    o2 = _outline([("POSITIONING", "positioning",
                    ["We win the premium niche on differentiation"])])
    picked2 = assign_frameworks(
        o2, "positioning strategy", None,
        choose=lambda ties: {t[0]: "bcg_matrix"})  # not a candidate
    assert picked2 == {}  # invalid pick -> NO framework, never a default

    o3 = _outline([("POSITIONING", "positioning",
                    ["We win the premium niche on differentiation"])])
    assert assign_frameworks(o3, "positioning strategy", None,
                             choose=None) == {}  # no chooser -> none


def test_tie_prompt_shows_avoid_and_shuffles_order():
    sig: set[str] = set()
    a, b = shortlist_for("positioning", sig)
    orders = set()
    for tag in ("ALPHA", "BETA", "GAMMA", "DELTA"):
        p = ties_prompt([(tag, [f"claims for {tag}"], a, b)], "brief")
        assert "AVOID if:" in p and "choose if:" in p
        first = min((p.find(a.id), a.id), (p.find(b.id), b.id))[1]
        orders.add(first)
    assert len(orders) == 2  # both orderings occur across sections


# -- the collapse guard --------------------------------------------------------

def test_no_framework_dominates_the_shortlists():
    """Run the whole labelled corpus; if any single framework takes more
    than 25% of assignments, the selector has collapsed."""
    facts_small = FactTable.from_csv(PORTFOLIO_CSV)
    facts_rich = FactTable.from_csv(RICH_PORTFOLIO_CSV)
    cases = [
        ("portfolio_allocation", "allocate capital", facts_small),
        ("portfolio_allocation", "score six units on weighted criteria",
         facts_rich),
        ("portfolio_allocation", "which lines should we back?", None),
        ("market_attractiveness", "should we enter?", None),
        ("growth_path", "how do we grow?", None),
        ("positioning", "where do we win? (3cs)", None),
        ("positioning", "cost or differentiation lane?", None),
        ("org_execution", "can the org deliver?", None),
        ("cost_structure", "where is cost buried?", None),
        ("macro_risk", "which forces could break this?", None),
        ("problem_structuring", "why are we losing money?", None),
        ("category_creation", "escape the red ocean", None),
        ("stocktake", "where do we stand?", None),
    ]
    tie_flip = {"three_cs": 0, "porters_generic_strategies": 0}
    wins: Counter[str] = Counter()
    for i, (dt, brief, facts) in enumerate(cases):
        short = shortlist_for(dt, detect_signals(brief, facts))
        if len(short) == 2:  # alternate tie winners, as a fair chooser would
            pick = sorted(f.id for f in short)[i % 2]
            wins[pick] += 1
        elif len(short) == 1:
            wins[short[0].id] += 1
    del tie_flip
    total = sum(wins.values())
    assert total >= 10
    worst_id, worst_n = wins.most_common(1)[0]
    assert worst_n / total <= 0.25, (
        f"{worst_id} takes {worst_n}/{total} shortlists — the selector "
        f"has collapsed onto it")


# -- critics -------------------------------------------------------------------

def test_verdict_critic_flags_and_passes():
    o = _outline([("PORTFOLIO", "portfolio_allocation",
                   ["Our units differ a lot in performance levels"])])
    o.slides[1].framework = "bcg_matrix"
    assert any("verdict" in p for p in check_framework_verdicts(o))
    o.slides[1].claim = "Divest Gamma and double down on Alpha this year"
    assert check_framework_verdicts(o) == []


def test_slide_contract_flags_missing_cells_and_verdict():
    from deckengine.schema.slide_types import BulletContentSpec
    fw = FRAMEWORKS["bcg_matrix"]
    slide = BulletContentSpec(
        slide_type="bullet_content",
        title="Our portfolio spans several markets",
        bullets=[{"text": "Alpha leads the pack"}])
    probs = check_framework_slide(slide, fw)
    assert any("canonical parts" in p for p in probs)
    assert any("wallpaper" in p for p in probs)
    good = BulletContentSpec(
        slide_type="bullet_content",
        title="Invest in the Stars, harvest the Cash Cows, exit the Dogs",
        bullets=[{"text": "Stars: Alpha. Cash Cows: Beta. Question Marks: "
                          "Gamma. Dogs: none."}])
    assert check_framework_slide(good, fw) == []


# -- schema round trip (the approve-gate contract) -----------------------------

def test_outline_round_trip_preserves_fields_and_coerces_unknowns():
    o = _outline([("WHY", "market_attractiveness", ["Enter now"])])
    o.slides[1].framework = "porters_five_forces"
    back = Outline.model_validate(o.model_dump())
    assert back.slides[1].decision_type == "market_attractiveness"
    assert back.slides[1].framework == "porters_five_forces"
    # unknown ids coerce to None, never fail (trim-never-fail doctrine)
    weird = Outline.model_validate({
        "governing_thought": "g", "slides": [
            {"slide_type": "chart_slide", "claim": "A claim that asserts",
             "decision_type": "Market Attractiveness",
             "framework": "the-bcg"},
            {"slide_type": "title", "claim": "Cover"}]})
    assert weird.slides[0].decision_type == "market_attractiveness"
    assert weird.slides[0].framework is None


def test_facts_structure_helpers():
    facts = FactTable.from_csv(PORTFOLIO_CSV)
    assert "market_share" in facts.column_slugs()
    assert "growth" in facts.column_slugs()
    assert facts.unit_count() == 3
    assert FactTable().unit_count() == 0

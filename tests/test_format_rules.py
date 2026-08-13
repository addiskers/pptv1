"""Format-brain calibration: rules fire on the claims they encode, near
misses stay silent, and slide lint catches objective data-shape errors."""
from deckengine.llm.facts import FactTable
from deckengine.llm.format_rules import (RULES, check_outline_formats,
                                         check_slide_format,
                                         decision_table_text, first_rule,
                                         signals_from)
from deckengine.llm.story import Outline, OutlineSlide
from deckengine.schema.slide_types import (BulletContentSpec, ChartSlideSpec,
                                           CustomLayoutSpec)

CSV = """Segment,2021,2022,2023
Commuter,100,140,180
Premium,60,80,110
Cargo,40,60,75
"""
FACTS = FactTable.from_csv(CSV, source_label="ev.csv")


def _rule(claim, facts=None):
    return first_rule(signals_from(claim, facts))


def _series(values, name="s"):
    return {"name": name, "values": values}


def _chart(**kw):
    base = dict(chart_type="bar", categories=["A", "B", "C"],
                series=[_series([1, 2, 3])], sort="desc",
                highlight=None, annotation=None)
    base.update(kw)
    return base


# -- rule firing + ordering ---------------------------------------------------


def test_two_axis_matrix_beats_ranking():
    sig = signals_from("Premium leads the quadrant on attractiveness",
                       FACTS)
    assert sig.two_axis and sig.ranking and sig.entity_count == 3
    assert first_rule(sig).id == "two_axis_matrix"


def test_bridge_beats_correlation():
    claim = "EBITDA walks from $40M to $55M, driven by pricing"
    sig = signals_from(claim)
    assert sig.bridge and sig.correlation
    assert first_rule(sig).id == "bridge_waterfall"


def test_funnel_beats_ranking():
    claim = "Conversion halves from leads to bookings at the demo stage"
    assert _rule(claim, FACTS).id == "funnel_stages"


def test_options_scorecard_fires():
    r = _rule("Three entry modes are on the table: build, buy, partner")
    assert r.id == "options_scorecard"
    assert "n_column_comparison" in r.target_slide_types


def test_composition_fires_and_near_miss():
    assert _rule("Commuter accounts for 47% of the market").id == \
        "composition_share"
    near = signals_from("Shareholders approved the transaction")
    assert near.composition is False
    assert first_rule(near) is None


def test_trend_needs_periods():
    assert _rule("Revenue grew steadily since 2021", FACTS).id == \
        "trend_line"
    near = signals_from("A growth mindset defines the culture")
    assert near.trend is True          # the signal fires...
    assert first_rule(near) is None    # ...but no rule (no periods)


def test_ranking_needs_entities():
    assert _rule("Commuter leads the pack on volume", FACTS).id == \
        "ranking_bar"
    assert _rule("Commuter leads the pack on volume", None) is None


def test_distribution_and_correlation_teach_only():
    r = _rule("Incomes range from $900 to $1,500 across states")
    assert r.id == "distribution_histogram"
    r2 = _rule("Adoption scales with income")
    assert r2.id == "correlation_scatter"
    assert "scatter" in r2.then        # teach-only: names the gap


def test_hero_number_fires_and_near_miss():
    assert _rule("The white-space opportunity is worth $4.2B").id == \
        "hero_number"
    assert signals_from("A $12B prize sits in commuter EVs").hero_number
    assert signals_from("The team is worth backing").hero_number is False


def test_roadmap_and_process():
    assert _rule("Rollout reaches every region by Q3 2027").id == \
        "roadmap_timeline"
    claim = "Our approach runs in three phases from diagnostic to scale-up"
    assert _rule(claim).id == "process_chevron"


def test_dense_reference_needs_no_claim_signal():
    t8 = FactTable()
    for i in range(8):
        t8.add(f"row{i}_val", str((i + 1) * 11), f"value of state {i + 1}")
    assert _rule("Program results for every state at a glance", t8).id == \
        "dense_reference"
    assert _rule("The top states dominate spending", t8).id == \
        "ranking_bar"


# -- adversarial claims: lexicon precision ------------------------------------


def test_two_axis_needs_positioning_not_bare_position():
    # 'position' as market standing must not hijack rule #1 (specific-first)
    for claim in ("The ask buys a defensible #3 position by GMV",
                  "A 12% share position is worth $1.4B by 2029"):
        assert signals_from(claim).two_axis is False, claim
    assert _rule("The ask buys a defensible #3 position by GMV",
                 FACTS).id == "ranking_bar"
    assert signals_from(
        "Competitive positioning favors a focused launch").two_axis is True


def test_trend_movement_verbs():
    # bread-and-butter consulting movement verbs must fire the trend signal
    assert _rule("Attrition dropped from 18% to 12% after the program",
                 FACTS).id == "trend_line"
    assert _rule("Margins rose while volumes fell", FACTS).id == "trend_line"
    assert signals_from("Adoption is growing across metros").trend is True
    # ...but present-tense 'fall' stays with distribution, not trend
    dist = signals_from("Most fall between $900 and $1,500 per rider", FACTS)
    assert dist.trend is False and dist.distribution is True


# -- signals from a real FactTable -------------------------------------------


def test_signals_from_csv_fixture():
    sig = signals_from("Commuter leads the pack", FACTS)
    assert sig.n_periods == 3
    assert sig.share_facts == 9        # 3 rows x 3 year columns
    assert sig.entity_count == 3
    assert sig.crosses_zero is False and sig.has_targets is False


def test_signals_negatives_and_targets():
    t = FactTable()
    t.add("row0_ebit", "-12", "EBIT of Alpha")
    t.add("row1_ebit", "(4)", "EBIT of Beta vs target")
    sig = signals_from("", t)
    assert sig.crosses_zero is True
    assert sig.has_targets is True
    assert sig.entity_count == 2


def test_option_and_criteria_counts():
    s = signals_from(
        "Option A outperforms Option B when scored on cost, risk and speed")
    assert s.option_count == 2
    assert s.criteria_count == 3
    s2 = signals_from("Three routes were assessed for the board")
    assert s2.option_count == 3
    assert s2.criteria_count == 1      # cue without named criteria
    s3 = signals_from("The largest player wins")
    assert s3.option_count == 0 and s3.criteria_count == 0


# -- decision table for prompts -----------------------------------------------


def test_decision_table_text_cap_and_content():
    text = decision_table_text()
    assert len(text) <= 1800  # rules + the variant-hint tier
    lines = text.splitlines()
    assert lines[0].startswith("FORMAT SELECTION")
    assert "2x2" in text and "waterfall" in text and "line" in text
    # variant hints present
    assert "endpoint_labels" in text and "benchmark" in text
    assert "CHART STYLE" in text


# -- outline lint --------------------------------------------------------------


def test_outline_lint_flags_mistyped_ranking():
    outline = Outline(
        governing_thought="Enter the commuter EV segment now.",
        slides=[
            OutlineSlide(slide_type="title", claim="India EV market entry"),
            OutlineSlide(slide_type="bullet_content",
                         claim="Commuter leads the pack on volume"),
            OutlineSlide(slide_type="chart_slide",
                         claim="Premium grew fastest since 2021"),
        ])
    problems = check_outline_formats(outline, FACTS)
    assert len(problems) == 1
    assert "slide 2" in problems[0]
    assert "sort='desc'" in problems[0]


def test_outline_lint_skips_title_exempt():
    outline = Outline(
        governing_thought="Enter the commuter EV segment now.",
        slides=[
            OutlineSlide(slide_type="title",
                         claim="Commuter leads the pack on volume"),
            OutlineSlide(slide_type="section_divider",
                         claim="The market splits by segment share"),
            OutlineSlide(slide_type="chart_slide",
                         claim="Premium grew fastest since 2021"),
        ])
    assert check_outline_formats(outline, FACTS) == []


# -- slide lint: objective data-shape violations --------------------------------


def test_slide_lint_line_and_donut():
    line2 = ChartSlideSpec(
        title="Revenue doubled since 2021",
        chart=_chart(chart_type="line", categories=["2021", "2022"],
                     series=[_series([1, 2])], sort="none"))
    assert any("column chart" in p for p in check_slide_format(line2, None))
    donut7 = ChartSlideSpec(
        title="Revenue is fragmented across seven segments",
        chart=_chart(chart_type="donut", categories=list("ABCDEFG"),
                     series=[_series([30, 20, 15, 12, 10, 8, 5])]))
    assert any("max 6" in p for p in check_slide_format(donut7, None))
    bad_sum = ChartSlideSpec(
        title="Premium takes half the pool",
        chart=_chart(chart_type="donut", value_suffix="%",
                     series=[_series([50, 40, 30])]))
    assert any("95-105" in p for p in check_slide_format(bad_sum, None))
    good = ChartSlideSpec(
        title="Premium takes half the pool",
        chart=_chart(chart_type="donut", value_suffix="%",
                     series=[_series([47, 33, 20])]),
        footnote="Source: registry 2025 [[src:official]]")
    assert check_slide_format(good, None) == []


def test_slide_lint_stacked_series_ranking_highlight():
    stacked1 = ChartSlideSpec(
        title="Revenue held steady across segments",
        chart=_chart(chart_type="stacked_bar", sort="none"))
    assert any("plain bar" in p
               for p in check_slide_format(stacked1, None))
    four = ChartSlideSpec(
        title="Four segments move together",
        chart=_chart(series=[_series([1, 2, 3], name=f"s{i}")
                             for i in range(4)]))
    assert any("small multiples" in p for p in check_slide_format(four, None))
    unsorted = ChartSlideSpec(
        title="**Alpha leads** the market on volume",
        chart=_chart(categories=list("ABCDE"),
                     series=[_series([5, 4, 3, 2, 1])], sort="none"))
    assert any("sort='desc'" in p
               for p in check_slide_format(unsorted, None))
    sorted_ok = ChartSlideSpec(
        title="**Alpha leads** the market on volume",
        chart=_chart(categories=list("ABCDE"),
                     series=[_series([5, 4, 3, 2, 1])], sort="desc"),
        footnote="Source: registry 2025 [[src:official]]")
    assert check_slide_format(sorted_ok, None) == []
    ghost = ChartSlideSpec(
        title="Revenue held steady across segments",
        chart=_chart(highlight="Zeta"))
    assert any("not a category" in p for p in check_slide_format(ghost, None))


def test_slide_lint_custom_layout_and_clean_archetypes():
    slide = CustomLayoutSpec(
        title="Premium doubled while volume held",
        root={"kind": "cols", "children": [
            {"kind": "native_chart", "chart_type": "line",
             "categories": ["2021", "2022"],
             "series": [{"name": "Rev", "values": [1.0, 2.0]}],
             "sort": "none", "highlight": None, "annotation": None},
            {"kind": "text_block", "text": "Premium doubled."}]})
    assert any("column chart" in p for p in check_slide_format(slide, None))
    bullets = BulletContentSpec(title="Five moves de-risk the launch",
                                bullets=[{"text": "Move one"}])
    assert check_slide_format(bullets, None) == []


def test_slide_lint_deeply_nested_chart_and_chartless_tree():
    # chart buried under cols > panel > rows must still be found
    deep = CustomLayoutSpec(
        title="Premium doubled while volume held",
        root={"kind": "cols", "children": [
            {"kind": "panel", "child": {"kind": "rows", "children": [
                {"kind": "native_chart", "chart_type": "line",
                 "categories": ["2021", "2022"],
                 "series": [{"name": "Rev", "values": [1.0, 2.0]}],
                 "sort": "none", "highlight": None, "annotation": None},
                {"kind": "text_block", "text": "Premium doubled."}]}},
            {"kind": "text_block", "text": "Volume held."}]})
    assert any("column chart" in p for p in check_slide_format(deep, None))
    # a custom layout without any chart lints clean
    no_chart = CustomLayoutSpec(
        title="Two proof points anchor the ask",
        root={"kind": "cols", "children": [
            {"kind": "text_block", "text": "Proof one."},
            {"kind": "text_block", "text": "Proof two."}]})
    assert check_slide_format(no_chart, None) == []


def test_signals_from_none_claim_and_empty_facts():
    empty = signals_from("", FactTable())
    assert empty.n_periods == 0 and empty.entity_count == 0
    assert empty.share_facts == 0
    assert first_rule(empty) is None
    assert first_rule(signals_from(None)) is None  # defensive: claim or ""

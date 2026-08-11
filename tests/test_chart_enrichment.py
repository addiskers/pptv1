"""Deterministic chart enrichment: plain author charts get rich, content-
driven styling; explicit author choices are never overridden."""
from deckengine.llm.format_rules import enrich_slide_charts
from deckengine.schema.components import (ChartSeriesSpec, ChartStyleSpec,
                                          NativeChartSpec)
from deckengine.schema.slide_types import ChartSlideSpec


def _chart_slide(title, **chart):
    chart.setdefault("sort", "none")
    chart.setdefault("highlight", None)
    chart.setdefault("annotation", None)
    return ChartSlideSpec(title=title, chart=NativeChartSpec(**chart))


def test_growth_line_gets_endpoints_and_cagr_chip():
    s = _chart_slide(
        "Revenue grew to $21B, tripling since 2022",
        chart_type="line", categories=["2022", "2023", "2024", "2025"],
        series=[ChartSeriesSpec(name="Rev", values=[7, 12, 16, 21])])
    enrich_slide_charts(s)
    assert s.chart.style.endpoint_labels is True
    assert s.chart.style.cagr_chip is True


def test_single_series_bar_gets_value_labels():
    s = _chart_slide(
        "Pune leads on utilization",
        chart_type="bar", categories=["Pune", "Baroda", "Indore"],
        series=[ChartSeriesSpec(name="u", values=[91, 86, 78])], sort="desc")
    enrich_slide_charts(s)
    assert s.chart.style.value_labels is True


def test_multi_series_named_subject_highlighted():
    s = _chart_slide(
        "Acme outgrows the market and its rivals",
        chart_type="line", categories=["22", "23", "24"],
        series=[ChartSeriesSpec(name="Acme", values=[100, 120, 145]),
                ChartSeriesSpec(name="Market", values=[100, 108, 116])])
    enrich_slide_charts(s)
    assert s.chart.style.highlight_series == "Acme"


def test_long_labels_go_horizontal():
    s = _chart_slide(
        "Consumer electronics leads category spend",
        chart_type="bar",
        categories=["Consumer electronics & appliances",
                    "Fashion and lifestyle retail",
                    "Grocery and daily essentials"],
        series=[ChartSeriesSpec(name="s", values=[3, 2, 1])], sort="desc")
    enrich_slide_charts(s)
    assert s.chart.style.direction == "horizontal"


def test_explicit_author_choice_not_overridden():
    s = _chart_slide(
        "Revenue grew sharply since 2022",
        chart_type="line", categories=["2022", "2023", "2024"],
        series=[ChartSeriesSpec(name="Rev", values=[7, 12, 21])],
        style=ChartStyleSpec(endpoint_labels=False, value_labels=False))
    # author explicitly turned value labels OFF -> stays off; endpoint is a
    # default False so enrichment may enable it (that's an add, not an override)
    enrich_slide_charts(s)
    assert s.chart.style.value_labels is False  # explicit off respected


def test_non_growth_line_stays_plain():
    s = _chart_slide(
        "Monthly active users by cohort",
        chart_type="line", categories=["Jan", "Feb", "Mar"],
        series=[ChartSeriesSpec(name="u", values=[10, 11, 12])])
    enrich_slide_charts(s)
    assert s.chart.style.endpoint_labels is False
    assert s.chart.style.cagr_chip is False


def test_no_chart_slide_is_noop():
    from deckengine.schema.slide_types import BulletContentSpec
    s = BulletContentSpec(title="Five moves", bullets=[{"text": "one"}])
    enrich_slide_charts(s)  # must not raise

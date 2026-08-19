"""The chart & exhibit CANON — every visual form famous consulting decks
use, as data.

One shared vocabulary serving three consumers:
- the corpus form census (T4) classifies real big-firm slides against
  these ids;
- the primitive build backlog = census frequency × status=="gap";
- prompts/routing cite the same names end to end.

status:
- "primitive"  — a dedicated engine renderer exists (`engine` names it)
- "composable" — buildable today from canvas elements / existing pieces
- "gap"        — not yet buildable well; a build-backlog entry
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonForm:
    id: str
    family: str          # comparison|composition|trend|distribution|
    #                      relationship|flow|deviation|multi_criteria|
    #                      diagram|number
    signals: str         # what message calls for it (prompt/routing text)
    status: str          # primitive|composable|gap
    engine: str | None   # component kind / chart_type / recipe when not gap


_C = CanonForm
CANON: dict[str, CanonForm] = {f.id: f for f in [
    # -- comparison ---------------------------------------------------------
    _C("ranking_bar", "comparison", "who is biggest; ranked entities",
       "primitive", "native_chart:bar sort=desc"),
    _C("grouped_bar", "comparison", "2-3 metrics across the same entities",
       "primitive", "native_chart:bar multi-series"),
    _C("paired_bar", "comparison", "before/after or A-vs-B per entity",
       "primitive", "native_chart:bar 2 series"),
    _C("dot_plot", "comparison", "many entities, one metric, compact",
       "composable", "xy_chart (value as x, rank as y)"),
    _C("bullet", "comparison", "actual vs target in one bar",
       "gap", None),
    _C("tornado_butterfly", "comparison",
       "two populations/scenarios back-to-back", "gap", None),
    _C("heat_table", "comparison", "entities x criteria with intensity",
       "primitive", "data_table cell_kind=heatmap"),
    # -- composition --------------------------------------------------------
    _C("donut", "composition", "parts of a whole, <=6 parts",
       "primitive", "native_chart:donut"),
    _C("stacked_100", "composition", "composition compared across entities",
       "primitive", "native_chart:stacked_bar percent_100"),
    _C("stacked_bar", "composition", "absolute totals + their mix",
       "primitive", "native_chart:stacked_bar"),
    _C("buildup_waterfall", "composition", "how parts sum to the total",
       "primitive", "native_chart:waterfall"),
    _C("mekko", "composition",
       "TWO dimensions of composition at once (segment size x share) — "
       "the market-map king", "gap", None),
    _C("treemap", "composition", "many-part composition by area",
       "gap", None),
    _C("area_stack", "composition", "composition evolving over time",
       "gap", None),
    _C("pyramid", "composition", "tiered/hierarchical composition",
       "primitive", "pyramid"),
    # -- trend --------------------------------------------------------------
    _C("line", "trend", "continuous trend, few series",
       "primitive", "native_chart:line"),
    _C("indexed_line", "trend", "relative growth from a =100 base",
       "composable", "native_chart:line (index the data)"),
    _C("column_trend", "trend", "few periods, discrete emphasis",
       "primitive", "native_chart:bar over periods"),
    _C("combo_line_column", "trend",
       "two units on one timeline (revenue columns + margin% line)",
       "primitive", "native_chart:combo style.combo_line_series"),
    _C("slope", "trend", "two-period change, many entities — brutal clarity",
       "gap", None),
    _C("fan_forecast", "trend", "forecast with uncertainty band",
       "composable", "native_chart:line forecast_from (dashes the tail)"),
    _C("sparkline_table", "trend", "in-table micro-trends",
       "gap", None),
    _C("bump", "trend", "rank positions over time", "gap", None),
    _C("s_curve", "trend", "adoption/maturity trajectory",
       "composable", "native_chart:line shaped data + annotation"),
    # -- distribution -------------------------------------------------------
    _C("histogram", "distribution", "shape of a distribution",
       "composable", "native_chart:bar of bins"),
    _C("box_plot", "distribution", "spread + outliers across groups",
       "gap", None),
    _C("pareto", "distribution", "the vital few (80/20) drawn",
       "gap", None),
    # -- relationship -------------------------------------------------------
    _C("scatter", "relationship", "does X relate to Y", "primitive",
       "xy_chart"),
    _C("bubble", "relationship",
       "X vs Y with size as the third variable (BCG engine)", "primitive",
       "xy_chart (points carry size)"),
    _C("quadrant_scatter", "relationship", "scatter + strategic quadrants",
       "primitive", "xy_chart quadrants=true + quadrant_labels"),
    # -- flow ---------------------------------------------------------------
    _C("bridge_waterfall", "flow", "value walk A->B (EBITDA, price-volume)",
       "primitive", "native_chart:waterfall"),
    _C("sankey", "flow", "flows between states (value pools, migration)",
       "gap", None),
    _C("funnel", "flow", "staged conversion/pipeline",
       "primitive", "funnel"),
    # -- deviation ----------------------------------------------------------
    _C("diverging_bar", "deviation", "+/- vs plan or zero",
       "primitive", "native_chart:bar (auto diverging on signs)"),
    _C("sensitivity_tornado", "deviation", "which assumption moves the answer",
       "gap", None),
    # -- multi-criteria -----------------------------------------------------
    _C("radar", "multi_criteria", "3-8 criteria profile comparison",
       "gap", None),
    _C("harvey_matrix", "multi_criteria", "entities x criteria, 0-4 fills",
       "primitive", "harvey_balls"),
    _C("rag_grid", "multi_criteria", "status across dimensions",
       "primitive", "data_table cell_kind=badge/heatmap"),
    _C("scorecard", "multi_criteria", "criteria with in-cell bars/scores",
       "composable", "data_table + heatmap cells"),
    # -- diagrams (drawings, not data plots) --------------------------------
    _C("matrix_2x2", "diagram", "two strategic dimensions, four postures",
       "primitive", "matrix_2x2"),
    _C("value_chain", "diagram", "sequential value-adding activities",
       "composable", "chevron_pathway + blocks"),
    _C("chevron_process", "diagram", "N-step process/phases",
       "primitive", "chevron_pathway"),
    _C("gantt", "diagram", "phases with dates/lanes over a time axis",
       "primitive", "gantt_row"),
    _C("flywheel", "diagram", "self-reinforcing loop", "primitive", "cycle"),
    _C("onion", "diagram", "concentric layers (core -> periphery)",
       "primitive", "onion"),
    _C("venn", "diagram", "overlap between 2-3 sets", "primitive", "venn"),
    _C("temple", "diagram", "goal roof on capability pillars", "gap", None),
    _C("iceberg", "diagram", "visible symptom vs hidden mass", "gap", None),
    _C("staircase", "diagram", "step-wise value build to an outcome",
       "primitive", "staircase"),
    _C("hub_spoke", "diagram", "center + radiating elements", "primitive",
       "hub_spoke"),
    _C("issue_tree", "diagram", "question decomposed into branches (MECE)",
       "primitive", "tree variant=issue"),
    _C("driver_tree", "diagram", "KPI decomposed into drivers (math tree)",
       "primitive", "tree variant=driver (+/x operator chips)"),
    _C("decision_tree", "diagram", "branching choices with outcomes",
       "gap", None),
    _C("three_horizons", "diagram", "now/next/future growth waves",
       "composable", "custom_layout 3 panels + s_curve lines"),
    _C("journey_map", "diagram", "experience across stages",
       "composable", "timeline_row + blocks"),
    _C("stage_gate", "diagram", "phases with go/no-go gates",
       "composable", "chevron_pathway + markers"),
    _C("swot", "diagram", "strengths/weaknesses/opportunities/threats",
       "composable", "matrix_2x2 with labeled quadrants"),
    _C("map_geo", "diagram", "geography as the argument",
       "gap", None),
    _C("gauge", "diagram", "single score against a scale", "gap", None),
    _C("timeline_milestones", "diagram", "dated milestones on a rule",
       "primitive", "timeline_row"),
    # -- number-forward -----------------------------------------------------
    _C("big_number", "number", "one hero figure carries the slide",
       "primitive", "canvas_text size_pt>=48 / stat_row"),
    _C("kpi_cards", "number", "3-6 headline stats as cards",
       "primitive", "kpi_card_strip"),
    _C("icon_stat_rail", "number", "stats with icon anchors",
       "primitive", "icon_stat_row / icon_tile_row"),
    _C("progress", "number", "completion toward a goal",
       "primitive", "progress_pill / donut_stat"),
]}


def gaps() -> list[str]:
    """Build-backlog candidates, to be ranked by the corpus census."""
    return [f.id for f in CANON.values() if f.status == "gap"]


def census_vocabulary() -> list[str]:
    """The taxonomy the corpus form census classifies against."""
    return list(CANON) + ["photo_hero", "text_only", "other"]

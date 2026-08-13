"""Pydantic models for every component. These are the LLM contract AND the
component input type — components never see raw dicts.

Length bounds are generous sanity caps (2-3x typical), per the review: precise
enforcement happens via a measure-only fit_text pass, not character counting.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, Field

RichStr = str  # markdown-lite: **bold**, *italic*, [[role]]text[[/]]


def _strip_markup(v):
    """LLMs love to bold everything; plain display fields silently drop markup."""
    if isinstance(v, str) and ("*" in v or "[[" in v):
        from .rich import plain
        return plain(v)
    return v


PlainStr = Annotated[str, BeforeValidator(_strip_markup)]


class TextBlockSpec(BaseModel):
    kind: Literal["text_block"] = "text_block"
    text: RichStr = Field(max_length=1200)
    size_role: Literal["title", "h2", "body", "small", "micro"] = "body"
    font_role: Literal["display", "body"] = "body"
    align: Literal["left", "center", "right"] = "left"
    color_role: str = "ink"
    max_lines: int | None = None


class StatSpec(BaseModel):
    label: PlainStr = Field(max_length=60)
    value: PlainStr = Field(max_length=24)
    underline: bool = True


class StatRowSpec(BaseModel):
    kind: Literal["stat_row"] = "stat_row"
    stats: list[StatSpec] = Field(min_length=1, max_length=5)


class BadgeChipSpec(BaseModel):
    kind: Literal["badge_chip"] = "badge_chip"
    code: str = Field(max_length=4)  # must exist in theme.badge_palette


class SectionHeaderSpec(BaseModel):
    kind: Literal["section_header"] = "section_header"
    # caps must be >= every slide-level title/subtitle cap (assemblers feed
    # slide fields straight into this component)
    # small-caps eyebrow line above the title (constant within a deck
    # section; flows from the outline, never invented per slide)
    kicker: PlainStr | None = Field(default=None, max_length=40)
    title: RichStr = Field(max_length=300)
    subtitle: RichStr | None = Field(default=None, max_length=500)
    rule: bool = True
    accent_subtitle: bool = True


class MiniTableSpec(BaseModel):
    kind: Literal["mini_table"] = "mini_table"
    headers: list[PlainStr] = Field(min_length=2, max_length=6)
    rows: list[list[PlainStr]] = Field(min_length=1, max_length=8)
    col_fracs: list[float] | None = None
    align: Literal["left", "center"] = "center"


class DataColumnSpec(BaseModel):
    label: RichStr = Field(max_length=80)
    frac: float = Field(gt=0, le=1)
    cell_kind: Literal["text", "number", "badge", "heatmap", "dot"] = "text"
    align: Literal["left", "center", "right"] = "left"


class DataGroupSpec(BaseModel):
    label: PlainStr = Field(max_length=40)
    rows: list[list[PlainStr]] = Field(min_length=1, max_length=30)


class DataTableSpec(BaseModel):
    kind: Literal["data_table"] = "data_table"
    columns: list[DataColumnSpec] = Field(min_length=2, max_length=10)
    groups: list[DataGroupSpec] = Field(min_length=1, max_length=15)
    heatmap_lo: float = 0.0
    heatmap_hi: float = 100.0
    header_fill_role: str = "primary"
    zebra: bool = False
    # widen col 0 (capped +25%) when group labels would clip; explicit
    # opt-out for authors who want their fracs untouched
    auto_widen_label_col: bool = True


class IconStatRowSpec(BaseModel):
    kind: Literal["icon_stat_row"] = "icon_stat_row"
    icon: str = Field(max_length=12, description=(
        "one of: person, people, money, growth, chart, leaf, building, "
        "target, globe, bulb, shield, clock, gear, handshake, truck, "
        "factory, document, calendar, warning, check, refresh, scale, "
        "award, flag, pin, cart, drop, rocket, network, lock"))
    stat: RichStr = Field(max_length=40)
    text: RichStr = Field(max_length=300)


class IconTileSpec(BaseModel):
    icon: str = Field(max_length=12)  # icon name (see IconStatRowSpec vocab)
    stat: RichStr = Field(max_length=40)
    text: RichStr = Field(max_length=200)


class IconTileRowSpec(BaseModel):
    kind: Literal["icon_tile_row"] = "icon_tile_row"
    tiles: list[IconTileSpec] = Field(min_length=1, max_length=6)
    banded: bool = True


class DonutStatSpec(BaseModel):
    kind: Literal["donut_stat"] = "donut_stat"
    value_pct: float = Field(ge=0, le=100)  # filled share of the ring
    center_text: PlainStr = Field(max_length=8)   # e.g. "50%"
    label: RichStr = Field(max_length=80)         # caption under/beside the ring
    # container knobs (set by kpi_card_strip on dark tiles; leave defaults)
    inverse: bool = False           # text in inverse_ink for dark surfaces
    hole_fill_role: str = "bg"      # hole matches the surface it sits on


class ProgressPillSpec(BaseModel):
    kind: Literal["progress_pill"] = "progress_pill"
    label: RichStr = Field(max_length=60)
    value_pct: float = Field(ge=0, le=100)
    display: PlainStr = Field(max_length=16)      # text on/next to the bar, e.g. "312M"
    target_display: PlainStr | None = Field(default=None, max_length=16)
    inverse: bool = False  # container knob: text in inverse_ink for dark surfaces


class KpiCardSpec(BaseModel):
    title: RichStr = Field(max_length=60)
    body: RichStr | None = Field(default=None, max_length=240)
    # micro-viz combo tile: a card can hold a small viz instead of body text
    # (the reference FMD tile — progress bar / donut inside a dark stat card)
    viz: Union[ProgressPillSpec, DonutStatSpec] | None = None


class KpiCardStripSpec(BaseModel):
    kind: Literal["kpi_card_strip"] = "kpi_card_strip"
    cards: list[KpiCardSpec] = Field(min_length=2, max_length=6)
    fill_role: str = "primary_dark"


class CalloutBandSpec(BaseModel):
    kind: Literal["callout_band"] = "callout_band"
    label: PlainStr | None = Field(default=None, max_length=40)
    icon: str | None = Field(default=None, max_length=4)
    segments: list[RichStr] = Field(min_length=1, max_length=5)


class BulletItemSpec(BaseModel):
    text: RichStr = Field(max_length=400)
    level: int = Field(default=0, ge=0, le=2)


class BulletListSpec(BaseModel):
    kind: Literal["bullet_list"] = "bullet_list"
    items: list[BulletItemSpec] = Field(min_length=1, max_length=12)
    size_role: Literal["body", "small"] = "body"


class FootnoteStripSpec(BaseModel):
    kind: Literal["footnote_strip"] = "footnote_strip"
    notes: list[PlainStr] = Field(min_length=1, max_length=8)


class LegendItemSpec(BaseModel):
    code: str = Field(max_length=4)
    label: PlainStr = Field(max_length=60)


class LegendRowSpec(BaseModel):
    kind: Literal["legend_row"] = "legend_row"
    items: list[LegendItemSpec] = Field(min_length=1, max_length=8)


class HighlightBoxSpec(BaseModel):
    kind: Literal["highlight_box"] = "highlight_box"
    title: RichStr = Field(max_length=200)
    body: RichStr | None = Field(default=None, max_length=600)
    fill_role: str = "surface_alt"
    accent_bar: bool = True


class MilestoneSpec(BaseModel):
    label: PlainStr = Field(max_length=40)
    date: PlainStr = Field(max_length=16)
    done: bool = False


class TimelineRowSpec(BaseModel):
    kind: Literal["timeline_row"] = "timeline_row"
    milestones: list[MilestoneSpec] = Field(min_length=2, max_length=8)


class ChevronPathwaySpec(BaseModel):
    kind: Literal["chevron_pathway"] = "chevron_pathway"
    steps: list[PlainStr] = Field(min_length=2, max_length=6)
    highlight_index: int | None = None  # accent-filled step


class NumberedBlockSpec(BaseModel):
    kind: Literal["numbered_block"] = "numbered_block"
    number: PlainStr = Field(max_length=3)        # "1", "1A", "2B"
    # 160 matches slide-title budgets: models consistently write block
    # titles as full assertions; the renderer shrink-fits them anyway
    title: RichStr = Field(max_length=160)
    body: RichStr | None = Field(default=None, max_length=400)


class TwoToneHeaderSpec(BaseModel):
    kind: Literal["two_tone_header"] = "two_tone_header"
    left: RichStr = Field(max_length=60)
    right: RichStr = Field(max_length=120)
    left_frac: float = Field(default=0.35, gt=0.1, lt=0.9)


class ChartSeriesSpec(BaseModel):
    name: PlainStr = Field(max_length=40)
    values: list[float] = Field(min_length=1, max_length=24)


class BenchmarkLineSpec(BaseModel):
    value: float
    label: PlainStr = Field(max_length=24)  # e.g. "industry avg"


class ChartStyleSpec(BaseModel):
    """Rendering-variant knobs (the '30 ways' layer). Everything defaults
    off/auto so existing specs render unchanged; corpus style priors steer
    the LLM's choices and the engine computes any numbers itself."""
    value_labels: bool | None = Field(default=None, description=(
        "label every point/bar with its value; null = auto (on for "
        "single-series — the 91%-of-top-decks default)"))
    endpoint_labels: bool = Field(default=False, description=(
        "line charts: label only the first and last points"))
    highlight_series: PlainStr | None = Field(default=None, max_length=40,
        description="series name to keep in accent while others mute to gray")
    forecast_from: PlainStr | None = Field(default=None, max_length=24,
        description="category where the future starts; the line beyond it "
                    "renders dashed")
    benchmark: BenchmarkLineSpec | None = Field(default=None, description=(
        "dashed horizontal reference line at a value, with a label"))
    cagr_chip: bool = Field(default=False, description=(
        "corner chip stating the CAGR between first and last values — "
        "computed by the engine, never by the model"))
    percent_100: bool = Field(default=False, description=(
        "stacked bars normalized to 100%"))
    direction: Literal["vertical", "horizontal"] = "vertical"
    compact: bool = Field(default=False, description=(
        "micro sizing for multi-chart slides: smaller fonts, no legend"))


class NativeChartSpec(BaseModel):
    """A chart must ARGUE, not just plot: sort, highlight and annotation are
    required decisions (explicitly 'none' if deliberately unused).
    waterfall: values are SIGNED contributions; first category is the
    opening level and the last category is the closing total (the engine
    verifies the arithmetic and floats the middle bars)."""
    kind: Literal["native_chart"] = "native_chart"
    chart_type: Literal["bar", "stacked_bar", "line", "donut", "waterfall"]
    categories: list[PlainStr] = Field(min_length=1, max_length=24)
    series: list[ChartSeriesSpec] = Field(min_length=1, max_length=6)
    sort: Literal["desc", "asc", "none"] = Field(
        description="Sort categories by first series so the shape supports the "
                    "claim; 'none' only for time series / inherent order")
    highlight: PlainStr | None = Field(
        description="Category name to emphasize in accent color (the one data "
                    "point that proves the slide title), or null")
    annotation: PlainStr | None = Field(
        max_length=160,
        description="One short callout stating what the chart proves, or null")
    source: Annotated[
        str, BeforeValidator(lambda v: v[:140] if isinstance(v, str) else v)
    ] | None = Field(
        default=None, max_length=140,
        description="Per-chart provenance line, e.g. 'Source: IEA 2025 "
                    "[[src:official]]' — rendered as a micro line under the "
                    "chart (annotation carries rhetoric; source carries "
                    "provenance). Overlong values trim: the render ellipsizes "
                    "this line anyway, so length must never fail a slide.")
    value_suffix: PlainStr = Field(default="", max_length=8)  # e.g. "%", " Mn"
    style: ChartStyleSpec = Field(default_factory=ChartStyleSpec)


# --- comparison_columns: recursive children -----------------------------

ComparisonCell = Union[StatRowSpec, TextBlockSpec, MiniTableSpec]


class ComparisonColumnSpec(BaseModel):
    header: PlainStr = Field(max_length=40)
    cells: list[ComparisonCell] = Field(min_length=1, max_length=6)


class ComparisonColumnsSpec(BaseModel):
    kind: Literal["comparison_columns"] = "comparison_columns"
    columns: list[ComparisonColumnSpec] = Field(min_length=2, max_length=4)
    row_labels: list[str] | None = None  # left rail, one per cell row
    header_fill_role: str = "primary"
    dashed_separators: bool = True


class ArrowStatSpec(BaseModel):
    value: PlainStr = Field(max_length=16)        # oversized number, e.g. "185"
    label: RichStr = Field(max_length=100)


class ArrowCalloutSpec(BaseModel):
    """Lead box + arrow head pointing at big trailing stats (the reference
    deck's beige '$336M deployed' band)."""
    kind: Literal["arrow_callout"] = "arrow_callout"
    title: RichStr = Field(max_length=200)
    sub: RichStr | None = Field(default=None, max_length=300)
    stats: list[ArrowStatSpec] = Field(default_factory=list, max_length=4)
    fill_role: str = "surface_alt"


class BraceGroupSpec(BaseModel):
    """Stacked content grouped by a right brace to a single takeaway — the
    hand-built 'this table means THIS' gesture machines never make."""
    kind: Literal["brace_group"] = "brace_group"
    content: list[ComparisonCell] = Field(min_length=1, max_length=4)
    takeaway: RichStr = Field(max_length=200)
    takeaway_frac: float = Field(default=0.30, gt=0.15, lt=0.5)


class ImageBlockSpec(BaseModel):
    """Embedded image, aspect-fit, measured like any component. A missing
    asset renders a themed placeholder and warns — never blocks the deck."""
    kind: Literal["image_block"] = "image_block"
    src: str = Field(max_length=260, description=(
        "file name under the repo assets/ (or assets/samples/) folder, "
        "or an absolute path"))
    caption: RichStr | None = Field(default=None, max_length=200)
    height_in: float = Field(default=2.2, ge=0.6, le=6.0)
    fit: Literal["contain", "cover"] = "contain"


class FunnelStageSpec(BaseModel):
    label: PlainStr = Field(max_length=40)
    value: PlainStr = Field(max_length=16)


class FunnelSpec(BaseModel):
    """Top-down funnel: centered bands narrowing stage by stage."""
    kind: Literal["funnel"] = "funnel"
    stages: list[FunnelStageSpec] = Field(min_length=3, max_length=6)
    fracs: list[float] | None = Field(default=None, description=(
        "band width shares of full width, one per stage, each in (0.25, 1]; "
        "None = linear taper 1.0 -> 0.35"))


class QuadrantSpec(BaseModel):
    title: RichStr = Field(max_length=60)
    items: list[PlainStr] = Field(min_length=1, max_length=4)


class Matrix2x2Spec(BaseModel):
    """First-class consulting 2x2: labeled axes + four quadrant panels."""
    kind: Literal["matrix_2x2"] = "matrix_2x2"
    x_label: PlainStr = Field(max_length=40)
    y_label: PlainStr = Field(max_length=40)
    quadrants: list[QuadrantSpec] = Field(
        min_length=4, max_length=4,
        description="order: top-left, top-right, bottom-left, bottom-right")
    highlight: int | None = Field(default=None, ge=0, le=3,
                                  description="accent-bordered quadrant index")


class HarveyItemSpec(BaseModel):
    label: PlainStr = Field(max_length=60)
    score: int = Field(ge=0, le=4)  # quarter-fills: 0=empty .. 4=full


class HarveyBallsSpec(BaseModel):
    """Row of harvey-ball ratings — the classic option-scoring vocabulary."""
    kind: Literal["harvey_balls"] = "harvey_balls"
    items: list[HarveyItemSpec] = Field(min_length=2, max_length=6)


ComponentSpec = Union[
    TextBlockSpec, StatRowSpec, BadgeChipSpec, SectionHeaderSpec, MiniTableSpec,
    DataTableSpec, IconStatRowSpec, KpiCardStripSpec, CalloutBandSpec,
    BulletListSpec, FootnoteStripSpec, LegendRowSpec, HighlightBoxSpec,
    ComparisonColumnsSpec, DonutStatSpec, ProgressPillSpec, TimelineRowSpec,
    ChevronPathwaySpec, NumberedBlockSpec, TwoToneHeaderSpec, NativeChartSpec,
    IconTileRowSpec, ArrowCalloutSpec, BraceGroupSpec, ImageBlockSpec,
    FunnelSpec, Matrix2x2Spec, HarveyBallsSpec,
]

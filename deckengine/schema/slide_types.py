"""Slide archetype specs — the discriminated union the LLM emits one of per slide."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

from .layout_tree import LayoutChild, check_tree

from .components import (
    ArrowCalloutSpec,
    BraceGroupSpec,
    BulletItemSpec,
    CalloutBandSpec,
    ChevronPathwaySpec,
    ComparisonColumnSpec,
    DataTableSpec,
    HighlightBoxSpec,
    IconStatRowSpec,
    KpiCardStripSpec,
    LegendRowSpec,
    NativeChartSpec,
    NumberedBlockSpec,
    RichStr,
    TimelineRowSpec,
)


class BgImage(BaseModel):
    """Mixin: faint watermark painted across the body band before content
    (the reference deck's state maps behind columns). Missing assets warn
    and skip — never block a render."""
    bg_image: str | None = Field(default=None, max_length=260)
    bg_image_opacity: float = Field(default=0.12, gt=0.02, le=0.5)


class TitleSlideSpec(BaseModel):
    slide_type: Literal["title"] = "title"
    title: RichStr = Field(max_length=160)
    subtitle: RichStr | None = Field(default=None, max_length=300)
    date: str | None = Field(default=None, max_length=40)
    org: str | None = Field(default=None, max_length=80)
    # full-bleed dark canvas with an oversized org wordmark bleeding off the
    # bottom edge, like a real cover slide (vs plain text on white)
    wordmark: str | None = Field(default=None, max_length=40)


class SectionDividerSpec(BaseModel):
    slide_type: Literal["section_divider"] = "section_divider"
    number: str | None = Field(default=None, max_length=4)
    title: RichStr = Field(max_length=140)
    subtitle: RichStr | None = Field(default=None, max_length=300)
    # "bleed": solid full-slide accent-colour panel (reference divider style);
    # "bar": the current left-bar style
    style: Literal["bleed", "bar"] = "bleed"


class BulletContentSpec(BgImage):
    slide_type: Literal["bullet_content"] = "bullet_content"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    bullets: list[BulletItemSpec] = Field(min_length=1, max_length=10)
    footnote: str | None = Field(default=None, max_length=300)


class ExecSectionSpec(BaseModel):
    heading: RichStr = Field(max_length=80)
    body: RichStr = Field(max_length=600)


class ExecSummarySpec(BgImage):
    slide_type: Literal["exec_summary"] = "exec_summary"
    title: RichStr = Field(max_length=220)
    sections: list[ExecSectionSpec] = Field(min_length=2, max_length=6)
    footnote: str | None = Field(default=None, max_length=300)


class NColumnComparisonSpec(BgImage):
    slide_type: Literal["n_column_comparison"] = "n_column_comparison"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    columns: list[ComparisonColumnSpec] = Field(min_length=2, max_length=4)
    row_labels: list[str] | None = None
    summary_band: CalloutBandSpec | None = None
    footnote: str | None = Field(default=None, max_length=300)


class KpiDashboardSpec(BgImage):
    slide_type: Literal["kpi_dashboard"] = "kpi_dashboard"
    title: RichStr = Field(max_length=220)
    # data table (or stats) braced to its takeaway — reference slide 4's
    # state table grouped by a bracket to the icon-stat rail
    brace_group: BraceGroupSpec | None = None
    icon_stats: list[IconStatRowSpec] = Field(default_factory=list, max_length=6)
    kpi_strip: KpiCardStripSpec | None = None
    # bottom band: lead box + arrow head + oversized trailing stats
    callout: ArrowCalloutSpec | None = None
    highlight: HighlightBoxSpec | None = None
    footnote: str | None = Field(default=None, max_length=300)


class DataDeepDiveSpec(BgImage):
    slide_type: Literal["data_deep_dive"] = "data_deep_dive"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    legend: LegendRowSpec | None = None
    table: DataTableSpec
    insights_heading: RichStr | None = Field(default=None, max_length=60)
    insights: list[BulletItemSpec] = Field(default_factory=list, max_length=8)
    footnote: str | None = Field(default=None, max_length=300)


class ChartSlideSpec(BgImage):
    slide_type: Literal["chart_slide"] = "chart_slide"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    chart: NativeChartSpec
    insights_heading: RichStr | None = Field(default=None, max_length=60)
    insights: list[BulletItemSpec] = Field(default_factory=list, max_length=6)
    footnote: str | None = Field(default=None, max_length=300)


class FrameworkSlideSpec(BgImage):
    slide_type: Literal["framework_slide"] = "framework_slide"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    pathway: ChevronPathwaySpec | None = None
    blocks: list[NumberedBlockSpec] = Field(min_length=1, max_length=6)
    footnote: str | None = Field(default=None, max_length=300)


class TimelineSlideSpec(BgImage):
    slide_type: Literal["timeline_slide"] = "timeline_slide"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    timeline: TimelineRowSpec
    phases: list[NumberedBlockSpec] = Field(default_factory=list, max_length=4)
    footnote: str | None = Field(default=None, max_length=300)


class StrategyOverviewSpec(BgImage):
    """The Gates slide-1 pattern: principles rail + dense pipeline table +
    goals sidebar."""
    slide_type: Literal["strategy_overview"] = "strategy_overview"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=500)
    legend: LegendRowSpec | None = None
    left_heading: RichStr = Field(max_length=80)
    principles: list[BulletItemSpec] = Field(min_length=2, max_length=8)
    table_heading: RichStr | None = Field(default=None, max_length=120)
    table: DataTableSpec
    sidebar_heading: RichStr = Field(max_length=60)
    goals: list[RichStr] = Field(min_length=2, max_length=4)
    cobenefits_heading: RichStr | None = Field(default=None, max_length=40)
    cobenefits: list[RichStr] = Field(default_factory=list, max_length=3)
    footnote: str | None = Field(default=None, max_length=400)


class CustomLayoutSpec(BgImage):
    """Escape hatch when no standard mold fits the claim: compose the body
    as a rows/cols/panel tree with any component as a leaf. Use standard
    archetypes first — this is for bespoke compositions (panel matrices,
    hero stat + proof stack, grid + summary band)."""
    slide_type: Literal["custom_layout"] = "custom_layout"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    root: LayoutChild
    footnote: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _tree_rails(self):
        problems = check_tree(self.root)
        if problems:
            raise ValueError("; ".join(problems))
        return self


SlideSpec = Annotated[
    Union[TitleSlideSpec, SectionDividerSpec, BulletContentSpec, ExecSummarySpec,
          NColumnComparisonSpec, KpiDashboardSpec, DataDeepDiveSpec,
          ChartSlideSpec, FrameworkSlideSpec, TimelineSlideSpec,
          StrategyOverviewSpec, CustomLayoutSpec],
    Field(discriminator="slide_type"),
]


class DeckMeta(BaseModel):
    title: str = Field(max_length=160)
    date: str | None = Field(default=None, max_length=40)
    footer_org: str | None = Field(default=None, max_length=80)
    confidentiality: str | None = Field(default=None, max_length=60)


class DeckSpec(BaseModel):
    schema_version: int = 1
    theme: str = "consulting_navy"
    meta: DeckMeta
    slides: list[SlideSpec] = Field(min_length=1, max_length=60)

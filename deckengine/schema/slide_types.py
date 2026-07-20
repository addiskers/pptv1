"""Slide archetype specs — the discriminated union the LLM emits one of per slide."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .components import (
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


class TitleSlideSpec(BaseModel):
    slide_type: Literal["title"] = "title"
    title: RichStr = Field(max_length=160)
    subtitle: RichStr | None = Field(default=None, max_length=300)
    date: str | None = Field(default=None, max_length=40)
    org: str | None = Field(default=None, max_length=80)


class SectionDividerSpec(BaseModel):
    slide_type: Literal["section_divider"] = "section_divider"
    number: str | None = Field(default=None, max_length=4)
    title: RichStr = Field(max_length=140)
    subtitle: RichStr | None = Field(default=None, max_length=300)


class BulletContentSpec(BaseModel):
    slide_type: Literal["bullet_content"] = "bullet_content"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    bullets: list[BulletItemSpec] = Field(min_length=1, max_length=10)
    footnote: str | None = Field(default=None, max_length=300)


class ExecSectionSpec(BaseModel):
    heading: RichStr = Field(max_length=80)
    body: RichStr = Field(max_length=600)


class ExecSummarySpec(BaseModel):
    slide_type: Literal["exec_summary"] = "exec_summary"
    title: RichStr = Field(max_length=220)
    sections: list[ExecSectionSpec] = Field(min_length=2, max_length=6)
    footnote: str | None = Field(default=None, max_length=300)


class NColumnComparisonSpec(BaseModel):
    slide_type: Literal["n_column_comparison"] = "n_column_comparison"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    columns: list[ComparisonColumnSpec] = Field(min_length=2, max_length=4)
    row_labels: list[str] | None = None
    summary_band: CalloutBandSpec | None = None
    footnote: str | None = Field(default=None, max_length=300)


class KpiDashboardSpec(BaseModel):
    slide_type: Literal["kpi_dashboard"] = "kpi_dashboard"
    title: RichStr = Field(max_length=220)
    icon_stats: list[IconStatRowSpec] = Field(default_factory=list, max_length=6)
    kpi_strip: KpiCardStripSpec | None = None
    highlight: HighlightBoxSpec | None = None
    footnote: str | None = Field(default=None, max_length=300)


class DataDeepDiveSpec(BaseModel):
    slide_type: Literal["data_deep_dive"] = "data_deep_dive"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    legend: LegendRowSpec | None = None
    table: DataTableSpec
    insights_heading: RichStr | None = Field(default=None, max_length=60)
    insights: list[BulletItemSpec] = Field(default_factory=list, max_length=8)
    footnote: str | None = Field(default=None, max_length=300)


class ChartSlideSpec(BaseModel):
    slide_type: Literal["chart_slide"] = "chart_slide"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    chart: NativeChartSpec
    insights_heading: RichStr | None = Field(default=None, max_length=60)
    insights: list[BulletItemSpec] = Field(default_factory=list, max_length=6)
    footnote: str | None = Field(default=None, max_length=300)


class FrameworkSlideSpec(BaseModel):
    slide_type: Literal["framework_slide"] = "framework_slide"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    pathway: ChevronPathwaySpec | None = None
    blocks: list[NumberedBlockSpec] = Field(min_length=1, max_length=6)
    footnote: str | None = Field(default=None, max_length=300)


class TimelineSlideSpec(BaseModel):
    slide_type: Literal["timeline_slide"] = "timeline_slide"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    timeline: TimelineRowSpec
    phases: list[NumberedBlockSpec] = Field(default_factory=list, max_length=4)
    footnote: str | None = Field(default=None, max_length=300)


class StrategyOverviewSpec(BaseModel):
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


SlideSpec = Annotated[
    Union[TitleSlideSpec, SectionDividerSpec, BulletContentSpec, ExecSummarySpec,
          NColumnComparisonSpec, KpiDashboardSpec, DataDeepDiveSpec,
          ChartSlideSpec, FrameworkSlideSpec, TimelineSlideSpec,
          StrategyOverviewSpec],
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

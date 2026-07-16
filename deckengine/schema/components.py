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


class IconStatRowSpec(BaseModel):
    kind: Literal["icon_stat_row"] = "icon_stat_row"
    icon: str = Field(max_length=12, description="a single emoji")
    stat: RichStr = Field(max_length=40)
    text: RichStr = Field(max_length=300)


class KpiCardSpec(BaseModel):
    title: RichStr = Field(max_length=60)
    body: RichStr = Field(max_length=240)


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


ComponentSpec = Union[
    TextBlockSpec, StatRowSpec, BadgeChipSpec, SectionHeaderSpec, MiniTableSpec,
    DataTableSpec, IconStatRowSpec, KpiCardStripSpec, CalloutBandSpec,
    BulletListSpec, FootnoteStripSpec, LegendRowSpec, HighlightBoxSpec,
    ComparisonColumnsSpec,
]

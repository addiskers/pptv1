"""icon_stat_row — impact-slide row: [icon circle | big stat | description].

Circle diameter equals the row height, and the row height depends on how the
description wraps in the width left over after the circle — a fixed point.
Layout runs a short, deterministic convergence loop in pure math shared by
measure() and render(), so both always agree exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, make_text_frame, write_fit_result, \
    write_spans_paragraph
from ..core.units import inch
from ..schema.components import IconStatRowSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_MIN_ROW_H = inch(0.42)
_PROBE_H = inch(11)        # generous probe: fit decides its own natural height
_STAT_FRAC = 0.22          # stat column share of the width right of the circle
_MIN_STAT_PT = 10.0
_MIN_DESC_PT = 7.5


@dataclass(frozen=True)
class _RowLayout:
    row_h: int
    gap: int
    stat_w: int
    desc_w: int
    stat_fit: FitResult
    desc_fit: FitResult


@register("icon_stat_row")
class IconStatRow(Component):
    spec_model = IconStatRowSpec

    # -- pure layout math (no side effects) -------------------------------

    def _fit_at(self, stat_spans: list[Span], desc_spans: list[Span],
                width: int, row_h: int, ctx: RenderContext,
                max_text_h: int = _PROBE_H) -> _RowLayout:
        gap = ctx.theme.spacing(0.6)
        remaining = max(0, width - row_h - gap)
        stat_w = round(remaining * _STAT_FRAC)
        desc_w = max(0, remaining - stat_w - gap)
        stat_fit = fit_text(stat_spans, BBox(0, 0, stat_w, max_text_h),
                            ctx.font("body"), max_size=ctx.size("stat"),
                            min_size=_MIN_STAT_PT, measurer=ctx.measurer)
        desc_fit = fit_text(desc_spans, BBox(0, 0, desc_w, max_text_h),
                            ctx.font("body"), max_size=ctx.size("small"),
                            min_size=_MIN_DESC_PT, measurer=ctx.measurer)
        return _RowLayout(row_h, gap, stat_w, desc_w, stat_fit, desc_fit)

    def _layout(self, data: IconStatRowSpec, width: int,
                ctx: RenderContext) -> _RowLayout:
        stat_spans = parse_rich(data.stat, base_color_role="ink")
        desc_spans = parse_rich(data.text, base_color_role="ink")
        row_h = _MIN_ROW_H
        for _ in range(3):
            lay = self._fit_at(stat_spans, desc_spans, width, row_h, ctx)
            need = max(lay.stat_fit.height_emu + ctx.theme.spacing(0.3),
                       lay.desc_fit.height_emu, _MIN_ROW_H)
            if need <= row_h:
                return lay
            row_h = need
        # rare non-convergence: settle at the last height, refit consistently
        return self._fit_at(stat_spans, desc_spans, width, row_h, ctx)

    # -- contract ----------------------------------------------------------

    def measure(self, data: IconStatRowSpec, width: int,
                ctx: RenderContext) -> int:
        return self._layout(data, width, ctx).row_h

    def render(self, slide, data: IconStatRowSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        lay = self._layout(data, bbox.w, ctx)
        if lay.row_h > bbox.h:
            # a canvas cell can be shorter than the natural row: CLAMP and
            # refit — text shrinks/ellipsizes inside the row (reported as
            # truncations); the row never paints over the neighbour below
            row_h = max(_MIN_ROW_H, bbox.h)
            lay = self._fit_at(parse_rich(data.stat, base_color_role="ink"),
                               parse_rich(data.text, base_color_role="ink"),
                               bbox.w, row_h, ctx, max_text_h=row_h)
        row = bbox.with_height(lay.row_h)

        # icon circle: diameter == row height
        circle, rest = row.take_left(lay.row_h)
        s = add_shape(slide, circle, theme, shape="oval",
                      fill_role="primary_dark")
        from ..core.icons import ICON_NAMES
        if data.icon in ICON_NAMES:
            # themed monochrome PNG icon (kills the emoji tell)
            from ..core.pptx_shapes import add_icon
            add_icon(slide, circle.inset(round(lay.row_h * 0.24)), data.icon,
                     theme, color_role="inverse_ink")
        else:
            tf = make_text_frame(s, align="center", anchor="middle")
            write_spans_paragraph(tf, [Span(data.icon, color_role="inverse_ink")],
                                  ctx.size("h2"), theme, family=ctx.font("body"),
                                  align="center")

        # big stat, vertically centered in the row
        _, rest = rest.take_left(lay.gap)
        stat_cell, rest = rest.take_left(lay.stat_w)
        if lay.stat_fit.truncated:
            ctx.report.truncated(f"icon_stat_row stat: {data.stat[:24]!r}")
        stat_box = add_text_box(slide, stat_cell, align="left", anchor="middle")
        write_fit_result(stat_box.text_frame, lay.stat_fit, theme,
                         family=ctx.font("body"), align="left",
                         default_color_role="ink")

        # description, vertically centered in the row
        _, desc_cell = rest.take_left(lay.gap)
        if lay.desc_fit.truncated:
            ctx.report.truncated(f"icon_stat_row text: {data.text[:40]!r}")
        desc_box = add_text_box(slide, desc_cell, align="left", anchor="middle")
        write_fit_result(desc_box.text_frame, lay.desc_fit, theme,
                         family=ctx.font("body"), align="left",
                         default_color_role="ink")

        if lay.row_h > bbox.h:
            ctx.report.warn("icon_stat_row: row taller than provided bbox")
        return lay.row_h

"""arrow_callout — lead box + arrow head + oversized trailing stats.

Reference look: the Gates impact slide's bottom band — a beige box ("AgDev has
deployed $336M in India"), a same-fill pentagon arrow pointing right, then big
stats separated by dashed rules. The protruding arrow is the hand-built tell;
machine decks put the conclusion in yet another rectangle.

measure(): band height = max(lead text + padding, tallest stat column, 1.0in).
render(): box, pentagon at its right edge, stat columns with dashed vlines.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, fit_text
from ..core.pptx_shapes import add_shape, add_vline
from ..core.pptx_text import (add_text_box, write_fit_result,
                              write_spans_paragraph)
from ..core.units import inch
from ..schema.components import ArrowCalloutSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_BOX_FRAC = 0.42          # lead box width share when stats are present
_ARROW_W = inch(0.5)
_ARROW_H_MAX = inch(0.55)
_MIN_BAND_H = inch(1.0)
_MIN_TITLE_PT = 9.0
_MIN_SUB_PT = 6.5
_MIN_VALUE_PT = 12.0
_MIN_LABEL_PT = 7.0
_PROBE_H = inch(11)


@dataclass(frozen=True)
class _Plan:
    box_w: int
    title_fit: FitResult
    sub_fit: FitResult | None
    stat_fits: tuple[tuple[FitResult, FitResult], ...]  # (value, label) per stat
    band_h: int


@register("arrow_callout")
class ArrowCallout(Component):
    spec_model = ArrowCalloutSpec

    # -- shared planning (side-effect free) --------------------------------

    def _plan(self, data: ArrowCalloutSpec, width: int,
              ctx: RenderContext) -> _Plan:
        theme = ctx.theme
        pad = theme.spacing(0.6)
        gap = theme.spacing(0.3)
        box_w = round(width * _BOX_FRAC) if data.stats else width - _ARROW_W
        inner_w = max(1, box_w - 2 * pad)
        title_fit = fit_text(parse_rich(data.title, base_color_role="ink"),
                             BBox(0, 0, inner_w, _PROBE_H), ctx.font("body"),
                             max_size=ctx.size("h2"), min_size=_MIN_TITLE_PT,
                             measurer=ctx.measurer)
        sub_fit = None
        text_h = title_fit.height_emu
        if data.sub:
            sub_fit = fit_text(parse_rich(data.sub, base_color_role="ink_muted"),
                               BBox(0, 0, inner_w, _PROBE_H), ctx.font("body"),
                               max_size=ctx.size("small"), min_size=_MIN_SUB_PT,
                               measurer=ctx.measurer)
            text_h += gap + sub_fit.height_emu

        stat_fits: list[tuple[FitResult, FitResult]] = []
        stats_h = 0
        if data.stats:
            stats_region_w = width - box_w - _ARROW_W - theme.spacing(0.6)
            cols = BBox(0, 0, max(1, stats_region_w), _PROBE_H).cols(
                len(data.stats), gap=theme.spacing(0.4))
            for stat, col in zip(data.stats, cols):
                cw = max(1, col.w - 2 * theme.spacing(0.4))
                vfit = fit_text(parse_rich(f"**{stat.value}**"),
                                BBox(0, 0, cw, _PROBE_H), ctx.font("body"),
                                max_size=ctx.size("title"),
                                min_size=_MIN_VALUE_PT, max_lines=1,
                                measurer=ctx.measurer)
                lfit = fit_text(parse_rich(stat.label),
                                BBox(0, 0, cw, _PROBE_H), ctx.font("body"),
                                max_size=ctx.size("small"),
                                min_size=_MIN_LABEL_PT, max_lines=2,
                                measurer=ctx.measurer)
                stat_fits.append((vfit, lfit))
                stats_h = max(stats_h, vfit.height_emu + gap + lfit.height_emu)

        band_h = max(text_h + 2 * pad, stats_h + 2 * pad, _MIN_BAND_H)
        return _Plan(box_w=box_w, title_fit=title_fit, sub_fit=sub_fit,
                     stat_fits=tuple(stat_fits), band_h=band_h)

    # -- contract -----------------------------------------------------------

    def measure(self, data: ArrowCalloutSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).band_h

    def render(self, slide, data: ArrowCalloutSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w, ctx)
        band_h = plan.band_h
        if band_h > bbox.h:
            ctx.report.warn(
                f"arrow_callout: band height {band_h} exceeds bbox height {bbox.h}")
        elif ctx.fill_hint and bbox.h > band_h:
            band_h = min(bbox.h, round(band_h * 1.4))
        pad = theme.spacing(0.6)
        gap = theme.spacing(0.3)
        family = ctx.font("body")

        # lead box + text
        box = BBox(bbox.x, bbox.y, plan.box_w, band_h)
        add_shape(slide, box, theme, shape="rect", fill_role=data.fill_role)
        tb = add_text_box(slide, box.inset(pad), anchor="middle")
        write_fit_result(tb.text_frame, plan.title_fit, theme, family=family,
                         default_color_role="ink")
        if plan.sub_fit is not None:
            for line in plan.sub_fit.lines:
                p = tb.text_frame.add_paragraph()
                write_spans_paragraph(
                    tb.text_frame, line.spans, plan.sub_fit.size_pt, theme,
                    family=family,
                    line_spacing_pt=plan.sub_fit.line_spacing_pt,
                    default_color_role="ink_muted", paragraph=p)

        # arrow head at the box's right edge, same fill — points at the stats
        arrow_h = min(_ARROW_H_MAX, round(band_h * 0.5))
        arrow = BBox(box.right, bbox.y + (band_h - arrow_h) // 2,
                     _ARROW_W, arrow_h)
        add_shape(slide, arrow, theme, shape="pentagon",
                  fill_role=data.fill_role)

        # trailing stats: value over label, dashed separators between columns
        if data.stats:
            region = BBox(arrow.right + theme.spacing(0.6), bbox.y,
                          bbox.right - arrow.right - theme.spacing(0.6), band_h)
            cols = region.cols(len(data.stats), gap=theme.spacing(0.4))
            for (vfit, lfit), col in zip(plan.stat_fits, cols):
                content_h = vfit.height_emu + gap + lfit.height_emu
                y = col.y + (band_h - content_h) // 2
                vbox = add_text_box(
                    slide, BBox(col.x, y, col.w, vfit.height_emu),
                    align="center")
                write_fit_result(vbox.text_frame, vfit, theme, family=family,
                                 align="center", default_color_role="ink")
                lbox = add_text_box(
                    slide, BBox(col.x, y + vfit.height_emu + gap, col.w,
                                lfit.height_emu), align="center")
                write_fit_result(lbox.text_frame, lfit, theme, family=family,
                                 align="center", default_color_role="ink")
            v_inset = theme.spacing(0.5)
            for j in range(len(cols) - 1):
                mid = (cols[j].right + cols[j + 1].x) // 2
                add_vline(slide, mid, bbox.y + v_inset, band_h - 2 * v_inset,
                          theme, role="ink_muted", weight_pt=0.75, dash="dash")
        return band_h

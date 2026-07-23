"""matrix_2x2 — first-class consulting 2x2 (impact/effort prioritisation).

Reference look: four surface panels on a tight grid with dashed midlines, a
rotated y-axis label in a left gutter and an x-axis label centered under the
grid. Direction lives in the label text ("Impact →") — no arrowheads.
Quadrant content is a bold primary title over small bulleted items; the
highlighted quadrant (if any) carries an accent outline.

measure(): pure fit_text math per quadrant. All four panels share ONE track
height = max quadrant content + padding (comparison_columns pattern), so the
grid can never desynchronise. render(): same _plan; with fill_hint the tracks
stretch toward bbox.h (capped 1.5x natural, content stays top-aligned).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_hline, add_shape, add_vline
from ..core.pptx_text import add_text_box, write_fit_result
from ..core.units import inch
from ..schema.components import Matrix2x2Spec, QuadrantSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_PROBE_H = 10_000_000       # fit decides real height; probe never truncates
_Y_GUTTER_W = inch(0.32)    # left rail for the rotated y-axis label
_X_GUTTER_H = inch(0.30)    # band under the grid for the x-axis label
_GLYPH = "•"
_TITLE_MIN = 8.0
_ITEM_MIN = 7.0
_LABEL_MIN = 6.5
_HIGHLIGHT_LINE_PT = 1.75


@dataclass(frozen=True)
class _QuadPlan:
    title_fit: FitResult
    item_fits: tuple[FitResult, ...]
    content_h: int


@dataclass(frozen=True)
class _Plan:
    """Grid arithmetic shared verbatim by measure() and render()."""
    grid_w: int
    col_offsets: tuple[int, ...]   # relative to bbox.x (gutter included)
    col_widths: tuple[int, ...]
    quads: tuple[_QuadPlan, ...]
    track_h: int
    gap: int                       # panel gap; also gap above the x-label
    pad: int
    total: int


@register("matrix_2x2")
class Matrix2x2(Component):
    spec_model = Matrix2x2Spec

    # -- shared planning (side-effect free) --------------------------------

    def _plan(self, data: Matrix2x2Spec, width: int,
              ctx: RenderContext) -> _Plan:
        gap = ctx.theme.spacing(0.35)
        pad = ctx.theme.spacing(0.6)
        title_gap = ctx.theme.spacing(0.3)
        item_gap = ctx.theme.spacing(0.2)
        family = ctx.font("body")
        grid_w = max(0, width - _Y_GUTTER_W)
        cols = BBox(_Y_GUTTER_W, 0, grid_w, _PROBE_H).cols(2, gap=gap)
        quads: list[_QuadPlan] = []
        content_max = 0
        for i, quad in enumerate(data.quadrants):
            inner = BBox(0, 0, max(1, cols[i % 2].w - 2 * pad), _PROBE_H)
            title_spans = [replace(s, bold=True) for s in
                           parse_rich(quad.title, base_color_role="primary")]
            title_fit = fit_text(title_spans, inner, family,
                                 max_size=ctx.size("body"),
                                 min_size=_TITLE_MIN, max_lines=2,
                                 measurer=ctx.measurer)
            item_fits = tuple(
                fit_text([Span(f"{_GLYPH}  ", color_role="primary"),
                          Span(item, color_role="ink")],
                         inner, family, max_size=ctx.size("small"),
                         min_size=_ITEM_MIN, max_lines=2,
                         measurer=ctx.measurer)
                for item in quad.items)
            content_h = (title_fit.height_emu + title_gap
                         + sum(f.height_emu for f in item_fits)
                         + item_gap * (len(item_fits) - 1))
            quads.append(_QuadPlan(title_fit, item_fits, content_h))
            content_max = max(content_max, content_h)
        track_h = content_max + 2 * pad
        total = 2 * track_h + gap + gap + _X_GUTTER_H
        return _Plan(grid_w=grid_w,
                     col_offsets=tuple(c.x for c in cols),
                     col_widths=tuple(c.w for c in cols),
                     quads=tuple(quads), track_h=track_h, gap=gap, pad=pad,
                     total=total)

    # -- contract -----------------------------------------------------------

    def measure(self, data: Matrix2x2Spec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: Matrix2x2Spec, bbox: BBox,
               ctx: RenderContext) -> int:
        plan = self._plan(data, bbox.w, ctx)
        theme = ctx.theme

        track_h = plan.track_h
        if plan.total > bbox.h:
            ctx.report.warn(
                f"matrix_2x2: height {plan.total} exceeds bbox {bbox.h}")
        elif ctx.fill_hint and bbox.h > plan.total:
            # flex: taller panels (capped 1.5x); content stays top-aligned
            track_h += min((bbox.h - plan.total) // 2,
                           round(plan.track_h * 0.5))
        grid_h = 2 * track_h + plan.gap
        grid_x = bbox.x + _Y_GUTTER_W

        for i, (quad, qp) in enumerate(zip(data.quadrants, plan.quads)):
            panel = BBox(bbox.x + plan.col_offsets[i % 2],
                         bbox.y + (i // 2) * (track_h + plan.gap),
                         plan.col_widths[i % 2], track_h)
            if data.highlight == i:
                add_shape(slide, panel, theme, shape="rect",
                          fill_role="surface", line_role="accent",
                          line_w_pt=_HIGHLIGHT_LINE_PT)
            else:
                add_shape(slide, panel, theme, shape="rect",
                          fill_role="surface")
            self._render_quadrant(slide, i, quad, qp,
                                  panel.inset(plan.pad), ctx)

        # dashed midlines spanning the grid only
        add_hline(slide, grid_x, bbox.y + track_h + plan.gap // 2,
                  plan.grid_w, theme, role="ink_muted", weight_pt=0.75,
                  dash="dash")
        mid_x = bbox.x + (plan.col_offsets[0] + plan.col_widths[0]
                          + plan.col_offsets[1]) // 2
        add_vline(slide, mid_x, bbox.y, grid_h, theme, role="ink_muted",
                  weight_pt=0.75, dash="dash")

        self._render_y_label(slide, data.y_label, bbox, grid_h, ctx)
        self._render_x_label(slide, data.x_label,
                             BBox(grid_x, bbox.y + grid_h + plan.gap,
                                  plan.grid_w, _X_GUTTER_H), ctx)
        return grid_h + plan.gap + _X_GUTTER_H

    # -- quadrant content ----------------------------------------------------

    def _render_quadrant(self, slide, idx: int, quad: QuadrantSpec,
                         qp: _QuadPlan, inner: BBox,
                         ctx: RenderContext) -> None:
        family = ctx.font("body")
        if qp.title_fit.truncated:
            ctx.report.truncated(
                f"matrix_2x2 quadrant {idx} title: {quad.title[:40]!r}")
        box = add_text_box(slide, BBox(inner.x, inner.y, inner.w,
                                       qp.title_fit.height_emu))
        write_fit_result(box.text_frame, qp.title_fit, ctx.theme,
                         family=family, default_color_role="primary")
        y = inner.y + qp.title_fit.height_emu + ctx.theme.spacing(0.3)
        item_gap = ctx.theme.spacing(0.2)
        for item, fit in zip(quad.items, qp.item_fits):
            if fit.truncated:
                ctx.report.truncated(
                    f"matrix_2x2 quadrant {idx} item: {item[:40]!r}")
            b = add_text_box(slide, BBox(inner.x, y, inner.w, fit.height_emu))
            write_fit_result(b.text_frame, fit, ctx.theme, family=family)
            y += fit.height_emu + item_gap

    # -- axis labels -----------------------------------------------------------

    def _label_fit(self, text: str, box: BBox, ctx: RenderContext) -> FitResult:
        return fit_text([Span(text, bold=True, color_role="ink_muted")],
                        box, ctx.font("body"), max_size=ctx.size("small"),
                        min_size=_LABEL_MIN, max_lines=1,
                        measurer=ctx.measurer)

    def _render_y_label(self, slide, label: str, bbox: BBox, grid_h: int,
                        ctx: RenderContext) -> None:
        # unrotated box is grid_h wide x gutter tall, centered on the grid's
        # vertical span; after rotation its extent lies inside the gutter
        fit = self._label_fit(label, BBox(0, 0, grid_h, _Y_GUTTER_W), ctx)
        if fit.truncated:
            ctx.report.truncated(f"matrix_2x2 y_label: {label!r}")
        cx = bbox.x + _Y_GUTTER_W // 2
        cy = bbox.y + grid_h // 2
        box = add_text_box(slide,
                           BBox(cx - grid_h // 2, cy - _Y_GUTTER_W // 2,
                                grid_h, _Y_GUTTER_W),
                           align="center", anchor="middle")
        box.rotation = 270
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("body"), align="center",
                         default_color_role="ink_muted")

    def _render_x_label(self, slide, label: str, band: BBox,
                        ctx: RenderContext) -> None:
        fit = self._label_fit(label, band, ctx)
        if fit.truncated:
            ctx.report.truncated(f"matrix_2x2 x_label: {label!r}")
        box = add_text_box(slide, band, align="center", anchor="middle")
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("body"), align="center",
                         default_color_role="ink_muted")

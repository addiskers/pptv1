"""comparison_columns — N columns of stacked child components on shared row tracks.

ROW-TRACK GRID: the cell at index i in EVERY column sits at the same y and is
given the same track height — the max over columns of that cell's measured
height. One wrapped cell can therefore never desynchronize rows across columns
(that misalignment is the instant tell of a machine-made deck).

Children are resolved through the component registry (get_component), so this
module never imports sibling component modules.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape, add_vline
from ..core.pptx_text import make_text_frame, write_fit_result, write_spans_paragraph
from ..core.units import inch
from ..schema.components import ComparisonColumnsSpec
from .base import Component, RenderContext, get_component, register

_RAIL_FRAC = 0.14          # left rail width = min(14% of bbox.w, 1.6in)
_RAIL_MAX_IN = 1.6
_PENT_MAX_IN = 0.62        # pentagon height cap within its track
_LABEL_MIN_PT = 6.5        # matches text_block's micro floor


@dataclass(frozen=True)
class _Plan:
    """Track arithmetic shared verbatim by measure() and render()."""
    rail_w: int                # 0 when no row labels
    col_offsets: tuple[int, ...]   # column x offsets relative to bbox.x
    col_widths: tuple[int, ...]
    header_h: int
    gap: int                   # spacing(0.4): column gap + gap under header
    track_gap: int             # spacing(0.45) between tracks
    track_hs: tuple[int, ...]
    total: int


@register("comparison_columns")
class ComparisonColumns(Component):
    spec_model = ComparisonColumnsSpec

    # -- shared layout math -------------------------------------------------

    def _plan(self, data: ComparisonColumnsSpec, width: int,
              ctx: RenderContext) -> _Plan:
        gap = ctx.theme.spacing(0.4)
        track_gap = ctx.theme.spacing(0.45)
        rail_w = (min(round(width * _RAIL_FRAC), inch(_RAIL_MAX_IN))
                  if data.row_labels else 0)
        # probe at x=0: cols() widths depend only on w/gap, never on x
        probe = BBox(0, 0, width, 1)
        _, col_region = probe.take_left(rail_w)
        col_boxes = col_region.cols(len(data.columns), gap=gap)

        header_h = ctx.measurer.line_height_emu(
            [Span("Hg", bold=True)], ctx.font("body"), ctx.size("small")) + gap

        n_tracks = max(len(col.cells) for col in data.columns)
        track_hs: list[int] = []
        for i in range(n_tracks):
            h = 0
            for col, box in zip(data.columns, col_boxes):
                if i < len(col.cells):
                    cell = col.cells[i]
                    h = max(h, get_component(cell.kind).measure(cell, box.w, ctx))
            track_hs.append(h)

        total = header_h + gap + sum(track_hs) + track_gap * (n_tracks - 1)
        return _Plan(rail_w=rail_w,
                     col_offsets=tuple(b.x for b in col_boxes),
                     col_widths=tuple(b.w for b in col_boxes),
                     header_h=header_h, gap=gap, track_gap=track_gap,
                     track_hs=tuple(track_hs), total=total)

    # -- contract -------------------------------------------------------------

    def measure(self, data: ComparisonColumnsSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: ComparisonColumnsSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        plan = self._plan(data, bbox.w, ctx)
        theme = ctx.theme
        family = ctx.font("body")

        # flex: when given more height than natural, grow tracks evenly
        # (children stay top-aligned; extra becomes breathing room between rows)
        track_hs = list(plan.track_hs)
        extra = max(0, bbox.h - plan.total) if ctx.fill_hint else 0
        if extra > 0 and track_hs:
            per = min(extra // len(track_hs),
                      round(max(track_hs) * 0.5))
            track_hs = [h + per for h in track_hs]
        total = (plan.header_h + plan.gap + sum(track_hs)
                 + plan.track_gap * (len(track_hs) - 1))

        # emphasis: the winning column (matched on header, case-insensitive)
        want = (data.highlight_column or "").strip().casefold()
        hi_col = next((i for i, c in enumerate(data.columns)
                       if want and c.header.strip().casefold() == want), -1)
        if want and hi_col < 0:
            ctx.report.warn(f"comparison_columns: highlight_column "
                            f"{data.highlight_column!r} matches no header")

        # header bands
        for ci, (col, off, w) in enumerate(zip(data.columns,
                                               plan.col_offsets,
                                               plan.col_widths)):
            band = BBox(bbox.x + off, bbox.y, w, plan.header_h)
            s = add_shape(slide, band, theme, shape="rect",
                          fill_role="accent" if ci == hi_col
                          else data.header_fill_role)
            tf = make_text_frame(s, align="center", anchor="middle")
            write_spans_paragraph(
                tf, [Span(col.header, bold=True, color_role="inverse_ink")],
                ctx.size("small"), theme, family=family, align="center",
                default_color_role="inverse_ink")

        # row tracks — same y and same height for cell i in every column
        y = bbox.y + plan.header_h + plan.gap
        for i, track_h in enumerate(track_hs):
            if data.row_labels and i < len(data.row_labels):
                self._render_rail_label(slide, data.row_labels[i],
                                        BBox(bbox.x, y, plan.rail_w, track_h), ctx)
            for col, off, w in zip(data.columns, plan.col_offsets,
                                   plan.col_widths):
                if i < len(col.cells):
                    cell = col.cells[i]
                    # child may consume less than track_h (top-aligned) — fine
                    get_component(cell.kind).render(
                        slide, cell, BBox(bbox.x + off, y, w, track_h), ctx)
            y += track_h + plan.track_gap

        if data.dashed_separators:
            for j in range(len(data.columns) - 1):
                left_edge = bbox.x + plan.col_offsets[j] + plan.col_widths[j]
                right_edge = bbox.x + plan.col_offsets[j + 1]
                add_vline(slide, (left_edge + right_edge) // 2, bbox.y,
                          total, theme, role="ink_muted", weight_pt=0.75,
                          dash="dash")

        # emphasis ring: full-height accent outline around the winner
        if hi_col >= 0:
            add_shape(slide,
                      BBox(bbox.x + plan.col_offsets[hi_col], bbox.y,
                           plan.col_widths[hi_col], total),
                      theme, shape="rect", line_role="accent",
                      line_w_pt=1.75)

        return total

    # -- left rail ------------------------------------------------------------

    def _render_rail_label(self, slide, label: str, track: BBox,
                           ctx: RenderContext) -> None:
        if track.w <= 0 or track.h <= 0:
            return
        pent_w = max(0, track.w - ctx.theme.spacing(0.4))
        pent_h = min(track.h, inch(_PENT_MAX_IN))
        pent = BBox(track.x, track.y + (track.h - pent_h) // 2, pent_w, pent_h)
        s = add_shape(slide, pent, ctx.theme, shape="pentagon",
                      fill_role="surface_alt")
        tf = make_text_frame(s, align="center", anchor="middle")
        inner = pent.inset(ctx.theme.spacing(0.3))
        fit = fit_text([Span(label, bold=True, color_role="ink")], inner,
                       ctx.font("body"), max_size=ctx.size("micro"),
                       min_size=_LABEL_MIN_PT, max_lines=3,
                       measurer=ctx.measurer)
        if fit.truncated:
            ctx.report.truncated(f"comparison_columns rail label: {label!r}")
        write_fit_result(tf, fit, ctx.theme, family=ctx.font("body"),
                         align="center", default_color_role="ink")

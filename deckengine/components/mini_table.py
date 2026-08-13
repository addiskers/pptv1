"""mini_table — compact shape-grid table: one header row + data rows.

Rendered as a SHAPE GRID (one rect per cell), never a native OOXML table:
native table row heights are only minimums that PowerPoint re-grows, which
breaks the measure()==render() contract. Every row shares one fixed height
(one 'micro' line + padding); cells are single-line by design.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import make_text_frame, write_spans_paragraph
from ..core.units import pt, to_pt
from ..schema.components import MiniTableSpec
from .base import Component, RenderContext, register

_GRID_W_PT = 0.5
_PAD_MULT = 0.3    # vertical cell padding, in theme spacing units
_INSET_MULT = 0.25  # horizontal text inset inside each cell, each side
_MIN_CELL = 6.0    # shrink floor for cell text before ellipsis
_WIDEN_CAP = 1.25  # label col may grow to at most 1.25x its equal share
_PROBE_H = 10_000_000


@register("mini_table")
class MiniTable(Component):
    spec_model = MiniTableSpec

    # -- shared math (side-effect free) -----------------------------------

    def _line_h(self, ctx: RenderContext) -> int:
        """One 'micro' line pitch; headers are bold, so take the max face."""
        return ctx.measurer.line_height_emu(
            [Span("Xg"), Span("Xg", bold=True)],
            ctx.font("body"), ctx.size("micro"))

    def _row_h(self, ctx: RenderContext) -> int:
        return self._line_h(ctx) + ctx.theme.spacing(_PAD_MULT)

    def _fracs(self, data: MiniTableSpec) -> list[float]:
        n = len(data.headers)
        if (data.col_fracs and len(data.col_fracs) == n
                and all(f > 0 for f in data.col_fracs)):
            total = sum(data.col_fracs)
            return [f / total for f in data.col_fracs]
        return [1.0] * n

    def _fracs_for(self, data: MiniTableSpec, width: int,
                   ctx: RenderContext) -> list[float]:
        """Explicit col_fracs pass through; default equal widths auto-widen
        the label column (col 0) toward its longest cell, capped at 1.25x
        the equal share — kills the 'ha, Patan, Mehsana' clipping class."""
        fracs = self._fracs(data)
        n = len(data.headers)
        if data.col_fracs is not None or n < 2 or width <= 0:
            return fracs
        inset = ctx.theme.spacing(_INSET_MULT)
        size = ctx.size("micro")
        family = ctx.font("body")
        need = max(
            ctx.measurer.span_width_emu(
                Span(r[0] if r else "", bold=i == 0), family, size)
            for i, r in enumerate([list(data.headers)]
                                  + [list(r) for r in data.rows]))
        equal = 1.0 / n
        want = (need + 2 * inset) / width
        first = min(max(equal, want), equal * _WIDEN_CAP)
        if first <= equal:
            return fracs
        rest = (1.0 - first) / (n - 1)
        return [first] + [rest] * (n - 1)

    # -- contract ----------------------------------------------------------

    def measure(self, data: MiniTableSpec, width: int, ctx: RenderContext) -> int:
        return (1 + len(data.rows)) * self._row_h(ctx)

    def render(self, slide, data: MiniTableSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        family = ctx.font("body")
        size = ctx.size("micro")
        row_h = self._row_h(ctx)
        spacing_pt = to_pt(self._line_h(ctx))
        inset = ctx.theme.spacing(_INSET_MULT)
        fracs = self._fracs_for(data, bbox.w, ctx)
        if data.col_fracs is not None and fracs == [1.0] * len(data.headers) \
                and data.col_fracs != [1.0] * len(data.headers):
            ctx.report.warn(
                f"mini_table: col_fracs {data.col_fracs!r} invalid for "
                f"{len(data.headers)} columns; using equal widths")

        all_rows: list[list[str]] = [list(data.headers)] + [list(r) for r in data.rows]
        if any(len(r) != len(data.headers) for r in data.rows):
            ctx.report.warn("mini_table: row length != header count; "
                            "short rows padded, extra cells dropped")

        # rows that would overflow the bbox are dropped (mirrors fit_text truncation)
        n_fit = min(len(all_rows), int((bbox.h + pt(1)) // row_h))
        if n_fit < len(all_rows):
            ctx.report.truncated(
                f"mini_table: {len(all_rows) - n_fit} row(s) dropped")

        tight_cells = 0
        y = bbox.y
        for r in range(n_fit):
            is_header = r == 0
            row = all_rows[r]
            cells = BBox(bbox.x, y, bbox.w, row_h).split_h(*fracs)
            for c, cell in enumerate(cells):
                text = row[c] if c < len(row) else ""
                shape = add_shape(slide, cell, ctx.theme, shape="rect",
                                  fill_role="bg", line_role="grid",
                                  line_w_pt=_GRID_W_PT)
                tf = make_text_frame(shape, align=data.align, anchor="middle")
                # single-line cells by contract: never let PowerPoint re-wrap
                # an overlong cell into a second line the layout didn't budget
                tf.word_wrap = False
                if not text:
                    continue
                tf.margin_left = inset
                tf.margin_right = inset
                # shrink -> ellipsize inside the cell; an overlong cell must
                # never spill under its neighbour (the old word_wrap=False
                # overflow was the evaluated deck's clipped-table bug)
                fit = fit_text([Span(text, bold=is_header, color_role="ink")],
                               BBox(0, 0, max(1, cell.w - 2 * inset),
                                    _PROBE_H), family, max_size=size,
                               min_size=_MIN_CELL, max_lines=1,
                               measurer=ctx.measurer)
                if fit.truncated:
                    tight_cells += 1
                    ctx.report.truncated(f"mini_table cell: {text[:40]!r}")
                write_spans_paragraph(
                    tf, fit.lines[0].spans if fit.lines else [], fit.size_pt,
                    ctx.theme, family=family, align=data.align,
                    line_spacing_pt=spacing_pt, default_color_role="ink")
            y += row_h
        if tight_cells:
            ctx.report.warn(
                f"mini_table: {tight_cells} cell(s) ellipsized at the "
                f"{_MIN_CELL}pt floor")
        return n_fit * row_h

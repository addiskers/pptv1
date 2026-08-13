"""timeline_row — horizontal roadmap of dated milestone markers on a rule.

A 1.5pt 'grid' hline runs the full width at the vertical middle of the marker
band. N markers sit evenly spaced along it (first center at 6% of the width,
last at 94%): done milestones are solid 'primary' dots, pending ones are
'bg'-filled with a 1.25pt 'primary' outline. Above each marker sits a single
centered micro 'ink_muted' date line; below, a bold micro 'ink' label fit to
at most two lines within the per-milestone column width (w/N).

Height is fixed regardless of label wrap: one date line + spacing(0.2) +
marker diameter + spacing(0.2) + two reserved label lines. measure() and
render() share that arithmetic exactly.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_hline, add_shape
from ..core.pptx_text import add_text_box, write_fit_result, write_spans_paragraph
from ..core.units import to_inch, to_pt
from ..schema.components import TimelineRowSpec
from .base import Component, RenderContext, register

_FIRST_FRAC = 0.06        # first marker center as a fraction of width
_LAST_FRAC = 0.94         # last marker center
_MARKER_D_MULT = 1.4      # marker oval diameter (spacing multiple)
_BAND_GAP_MULT = 0.2      # gap date->marker and marker->label
_RULE_W_PT = 1.5          # roadmap rule weight
_PENDING_LINE_PT = 1.25   # outline weight on pending markers
_MIN_MICRO = 6.5          # label shrink floor
_LABEL_LINES = 2          # label rows reserved in the fixed height
_PROBE_H = 10_000_000     # fit decides real height; probe never truncates


@register("timeline_row")
class TimelineRow(Component):
    spec_model = TimelineRowSpec

    # -- shared math (side-effect free) ------------------------------------

    def _bands(self, ctx: RenderContext) -> tuple[int, int, int, int]:
        """(date_line_h, marker_d, label_line_h, band_gap) in EMU."""
        family = ctx.font("body")
        size = ctx.size("micro")
        date_h = ctx.measurer.line_height_emu([Span("Ag")], family, size)
        label_h = ctx.measurer.line_height_emu([Span("Ag", bold=True)],
                                               family, size)
        return (date_h, ctx.theme.spacing(_MARKER_D_MULT), label_h,
                ctx.theme.spacing(_BAND_GAP_MULT))

    def _height(self, ctx: RenderContext) -> int:
        date_h, marker_d, label_h, gap = self._bands(ctx)
        return date_h + gap + marker_d + gap + _LABEL_LINES * label_h

    # -- contract ------------------------------------------------------------

    def measure(self, data: TimelineRowSpec, width: int,
                ctx: RenderContext) -> int:
        return self._height(ctx)

    def render(self, slide, data: TimelineRowSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        date_h, marker_d, label_h, gap = self._bands(ctx)
        height = date_h + gap + marker_d + gap + _LABEL_LINES * label_h
        if height > bbox.h:
            ctx.report.warn(
                f"timeline_row: needs {to_inch(height):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")

        family = ctx.font("body")
        size = ctx.size("micro")
        n = len(data.milestones)
        marker_top = bbox.y + date_h + gap
        label_top = marker_top + marker_d + gap
        step_frac = (_LAST_FRAC - _FIRST_FRAC) / max(1, n - 1)
        # date/label columns span the REAL center-to-center spacing
        # (0.88w/(n-1)), not w/n — ~17% more room at n=4, so long labels
        # wrap later; the edge clamp below keeps columns inside the bbox
        col_w = round(bbox.w * step_frac) if n > 1 else bbox.w

        # rule first so the markers sit on top of it
        add_hline(slide, bbox.x, marker_top + marker_d // 2, bbox.w, ctx.theme,
                  role="grid", weight_pt=_RULE_W_PT)

        for i, ms in enumerate(data.milestones):
            cx = bbox.x + round(bbox.w * (_FIRST_FRAC + i * step_frac))
            # per-milestone column, clamped inside the bbox (edge markers sit
            # closer to the border than half a column)
            left = max(bbox.x, cx - col_w // 2)
            right = min(bbox.right, cx + col_w // 2)
            col_x, col_ww = left, right - left

            if ms.done:
                add_shape(slide,
                          BBox(cx - marker_d // 2, marker_top, marker_d,
                               marker_d),
                          ctx.theme, shape="oval", fill_role="primary")
            else:
                add_shape(slide,
                          BBox(cx - marker_d // 2, marker_top, marker_d,
                               marker_d),
                          ctx.theme, shape="oval", fill_role="bg",
                          line_role="primary", line_w_pt=_PENDING_LINE_PT)

            # date: single centered micro line above the marker
            date_box = add_text_box(slide, BBox(col_x, bbox.y, col_ww, date_h),
                                    align="center")
            write_spans_paragraph(
                date_box.text_frame, [Span(ms.date, color_role="ink_muted")],
                size, ctx.theme, family=family, align="center",
                line_spacing_pt=to_pt(date_h), default_color_role="ink_muted")

            # label: bold, centered, at most two lines in the column width
            fit = fit_text([Span(ms.label, bold=True, color_role="ink")],
                           BBox(0, 0, col_ww, _PROBE_H), family,
                           max_size=size, min_size=_MIN_MICRO,
                           max_lines=_LABEL_LINES, measurer=ctx.measurer)
            if fit.truncated:
                ctx.report.truncated(f"timeline_row: {ms.label[:40]!r}")
            label_box = add_text_box(
                slide, BBox(col_x, label_top, col_ww, _LABEL_LINES * label_h),
                align="center")
            write_fit_result(label_box.text_frame, fit, ctx.theme,
                             family=family, align="center",
                             default_color_role="ink")
        return height

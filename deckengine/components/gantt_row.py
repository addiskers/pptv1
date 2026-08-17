"""gantt_row — phase bars over a period axis (the project-plan form).

One lane per item: rounded phase bar from start to end period, label on a
left rail, optional milestone diamond with a micro caption at the bar's
end, optional 'today' rule. Census: the form real roadmap slides use
where timeline_row's milestone dots aren't enough.

measure(): axis row + n lanes — pure arithmetic shared with render().
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape, add_vline
from ..core.pptx_text import add_text_box, write_fit_result, \
    write_spans_paragraph
from ..core.units import inch, to_inch, to_pt
from ..schema.components import GanttRowSpec
from .base import Component, RenderContext, register

_LANE_PAD_MULT = 0.35
_MIN_LANE_H = inch(0.34)
_RAIL_FRAC = 0.22      # left label rail share of width
_BAR_INSET_MULT = 0.12  # vertical inset of the bar inside its lane
_MIN_LABEL = 6.5
_PROBE_H = 10_000_000
_FILL = "primary"
_HI_FILL = "accent"


@dataclass(frozen=True)
class _Plan:
    axis_h: int
    lane_h: int
    total: int


@register("gantt_row")
class GanttRow(Component):
    spec_model = GanttRowSpec

    def _plan(self, data: GanttRowSpec, ctx: RenderContext) -> _Plan:
        micro_h = ctx.measurer.line_height_emu(
            [Span("Ag")], ctx.font("body"), ctx.size("micro"))
        axis_h = micro_h + ctx.theme.spacing(0.25)
        lane_h = max(micro_h + ctx.theme.spacing(_LANE_PAD_MULT),
                     _MIN_LANE_H)
        return _Plan(axis_h, lane_h,
                     axis_h + len(data.items) * lane_h)

    def measure(self, data: GanttRowSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, ctx).total

    def render(self, slide, data: GanttRowSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, ctx)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"gantt_row: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        family = ctx.font("body")
        size = ctx.size("micro")
        n_periods = len(data.periods)
        rail_w = round(bbox.w * _RAIL_FRAC)
        grid_x = bbox.x + rail_w
        grid_w = bbox.w - rail_w
        col_w = grid_w / n_periods
        micro_pt = to_pt(ctx.measurer.line_height_emu(
            [Span("Ag")], family, size))

        # axis: period labels + light column rules
        for pi, period in enumerate(data.periods):
            px = grid_x + round(pi * col_w)
            pbox = add_text_box(
                slide, BBox(px, bbox.y, round(col_w), plan.axis_h),
                align="center")
            write_spans_paragraph(
                pbox.text_frame, [Span(period, color_role="ink_muted")],
                size, theme, family=family, align="center",
                line_spacing_pt=micro_pt, default_color_role="ink_muted")
            if pi:  # rule at each period boundary
                add_vline(slide, px, bbox.y + plan.axis_h,
                          plan.total - plan.axis_h, theme, role="grid",
                          weight_pt=0.5)

        lanes_y = bbox.y + plan.axis_h
        bar_inset = theme.spacing(_BAR_INSET_MULT)
        for li, item in enumerate(data.items):
            ly = lanes_y + li * plan.lane_h
            start = max(0, min(item.start, n_periods - 1))
            end = max(start + 1, min(item.end, n_periods))
            if (item.start, item.end) != (start, end):
                ctx.report.warn(
                    f"gantt_row: {item.label!r} span clamped to the "
                    f"{n_periods}-period axis")
            # label rail
            lfit = fit_text([Span(item.label, bold=li == data.highlight_index)],
                            BBox(0, 0, max(1, rail_w - theme.spacing(0.4)),
                                 _PROBE_H), family, max_size=size,
                            min_size=_MIN_LABEL, max_lines=1,
                            measurer=ctx.measurer)
            if lfit.truncated:
                ctx.report.truncated(f"gantt_row label: {item.label!r}")
            lbox = add_text_box(slide, BBox(bbox.x, ly, rail_w, plan.lane_h),
                                anchor="middle")
            write_fit_result(lbox.text_frame, lfit, theme, family=family,
                             default_color_role="ink")
            # phase bar
            bar = BBox(grid_x + round(start * col_w), ly + bar_inset,
                       max(1, round((end - start) * col_w)
                           - theme.spacing(0.15)),
                       plan.lane_h - 2 * bar_inset)
            fill = _HI_FILL if li == data.highlight_index else _FILL
            add_shape(slide, bar, theme, shape="rounded", fill_role=fill,
                      corner_radius=0.5)
            # milestone diamond + caption at the bar end
            if item.milestone:
                d = min(plan.lane_h - 2 * bar_inset, theme.spacing(1.1))
                add_shape(slide,
                          BBox(bar.right - d // 2, ly
                               + (plan.lane_h - d) // 2, d, d),
                          theme, shape="diamond", fill_role="accent")
                cap_w = max(1, bbox.right - bar.right - d)
                if cap_w > theme.spacing(3):
                    cbox = add_text_box(
                        slide, BBox(bar.right + d, ly, cap_w, plan.lane_h),
                        anchor="middle")
                    write_spans_paragraph(
                        cbox.text_frame,
                        [Span(item.milestone, color_role="ink_muted")],
                        size, theme, family=family,
                        line_spacing_pt=micro_pt,
                        default_color_role="ink_muted")
        # today rule
        if data.today_index is not None and 0 <= data.today_index <= n_periods:
            tx = grid_x + round(data.today_index * col_w)
            add_vline(slide, tx, bbox.y + plan.axis_h,
                      plan.total - plan.axis_h, theme, role="negative",
                      weight_pt=1.25, dash="dash")
        return plan.total

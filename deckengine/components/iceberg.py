"""iceberg — visible symptom vs hidden mass (what you see is not what
drives it).

A small accent triangle rides above a dashed waterline; a much larger
inverted trapezoid sinks below in primary_dark. Visible labels sit right
of the tip; hidden labels stack inside the mass in inverse ink. The 1:3
above/below area ratio IS the argument.

measure(): tip + line + mass arithmetic shared via _plan.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_hline, add_shape
from ..core.pptx_text import add_text_box, write_fit_result
from ..core.units import inch, to_inch
from ..schema.components import IcebergSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_TIP_H = inch(0.85)
_MASS_H = inch(2.35)
_BERG_W_FRAC = 0.46        # iceberg width share; labels use the rest
_MIN_LABEL = 7.0
_PROBE_H = 10_000_000


@dataclass(frozen=True)
class _Plan:
    visible_fits: tuple[FitResult, ...]
    hidden_fits: tuple[FitResult, ...]
    total: int


@register("iceberg")
class Iceberg(Component):
    spec_model = IcebergSpec

    def _plan(self, data: IcebergSpec, width: int,
              ctx: RenderContext) -> _Plan:
        family = ctx.font("body")
        rail_w = max(1, round(width * (1 - _BERG_W_FRAC))
                     - ctx.theme.spacing(1.0))
        visible = tuple(
            fit_text([Span(s.text, bold=True, italic=s.italic,
                           color_role="ink")
                      for s in parse_rich(v, base_color_role="ink")],
                     BBox(0, 0, rail_w, _PROBE_H), family,
                     max_size=ctx.size("small"), min_size=_MIN_LABEL,
                     max_lines=2, measurer=ctx.measurer)
            for v in data.visible)
        mass_w = round(width * _BERG_W_FRAC * 0.82)
        hidden = tuple(
            fit_text([Span(s.text, bold=True, italic=s.italic,
                           color_role="inverse_ink")
                      for s in parse_rich(h,
                                          base_color_role="inverse_ink")],
                     BBox(0, 0, mass_w, _PROBE_H), family,
                     max_size=ctx.size("small"), min_size=_MIN_LABEL,
                     max_lines=1, measurer=ctx.measurer)
            for h in data.hidden)
        return _Plan(visible, hidden, _TIP_H + _MASS_H)

    def measure(self, data: IcebergSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: IcebergSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w, ctx)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"iceberg: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        family = ctx.font("body")
        berg_w = round(bbox.w * _BERG_W_FRAC)
        berg_x = bbox.x
        cx = berg_x + berg_w // 2
        water_y = bbox.y + _TIP_H

        # visible tip (accent triangle) above the line
        tip_w = round(berg_w * 0.42)
        add_shape(slide, BBox(cx - tip_w // 2, bbox.y, tip_w, _TIP_H),
                  theme, shape="triangle", fill_role="accent")
        # dashed waterline across the full component width
        add_hline(slide, bbox.x, water_y, bbox.w, theme, role="ink_muted",
                  weight_pt=1.25, dash="dash")
        # hidden mass: inverted trapezoid below (wide at the waterline)
        ms = add_shape(slide, BBox(berg_x, water_y, berg_w, _MASS_H),
                       theme, shape="trapezoid", fill_role="primary_dark")
        try:
            ms.adjustments[0] = 0.28
        except (IndexError, ValueError):
            pass
        ms.rotation = 180  # trapezoid narrows downward = the sunken berg

        # visible labels: right rail beside the tip
        rail_x = berg_x + berg_w + theme.spacing(1.0)
        rail_w = max(1, bbox.right - rail_x)
        vy = bbox.y + theme.spacing(0.3)
        for v, fit in zip(data.visible, plan.visible_fits):
            if fit.truncated:
                ctx.report.truncated(f"iceberg visible: {v[:40]!r}")
            box = add_text_box(slide, BBox(rail_x, vy, rail_w,
                                           fit.height_emu))
            write_fit_result(box.text_frame, fit, theme, family=family,
                             default_color_role="ink")
            vy += fit.height_emu + theme.spacing(0.3)

        # hidden labels: stacked inside the mass, centered
        n = len(plan.hidden_fits)
        stack_h = sum(f.height_emu for f in plan.hidden_fits) \
            + theme.spacing(0.35) * (n - 1)
        hy = water_y + (_MASS_H - stack_h) // 2
        for h, fit in zip(data.hidden, plan.hidden_fits):
            if fit.truncated:
                ctx.report.truncated(f"iceberg hidden: {h[:40]!r}")
            box = add_text_box(
                slide, BBox(cx - round(berg_w * 0.41), hy,
                            round(berg_w * 0.82), fit.height_emu),
                align="center")
            write_fit_result(box.text_frame, fit, theme, family=family,
                             align="center",
                             default_color_role="inverse_ink")
            hy += fit.height_emu + theme.spacing(0.35)
        return plan.total

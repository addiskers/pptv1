"""staircase — ascending steps ('stairway to value').

Census: the step-wise value-build form (maturity ladders, ambition
staircases). Steps rise left→right, bottom-aligned; each carries its
label inside (inverse ink) when the step is tall enough, else above its
riser; optional value sits at the step's top edge. The LAST step is the
outcome and takes the accent unless highlight_index says otherwise.

measure(): tallest step + value row — pure arithmetic shared with
render() via _plan.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, make_text_frame, \
    write_fit_result, write_spans_paragraph
from ..core.units import inch, to_inch
from ..schema.components import StaircaseSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_BASE_H = inch(0.7)        # first step height
_RISE = inch(0.5)          # height added per step
_STRETCH_CAP = 1.6         # fill_hint may scale the stairs up to this
_GAP_MULT = 0.12           # horizontal gap between steps
_MIN_LABEL = 7.0
_INSIDE_MIN_H = inch(0.8)  # steps shorter than this label above instead
_PROBE_H = 10_000_000
_FILL = "primary"
_HI_FILL = "accent"


@dataclass(frozen=True)
class _Plan:
    value_h: int
    total: int
    scale: float = 1.0

    def step_h(self, i: int) -> int:
        return round((_BASE_H + i * _RISE) * self.scale)


@register("staircase")
class Staircase(Component):
    spec_model = StaircaseSpec

    def _plan(self, data: StaircaseSpec, ctx: RenderContext,
              scale: float = 1.0) -> _Plan:
        n = len(data.steps)
        value_h = 0
        if any(s.value for s in data.steps):
            value_h = ctx.measurer.line_height_emu(
                [Span("Hg", bold=True)], ctx.font("body"),
                ctx.size("small")) + ctx.theme.spacing(0.2)
        total = value_h + round((_BASE_H + (n - 1) * _RISE) * scale)
        return _Plan(value_h, total, scale)

    def measure(self, data: StaircaseSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, ctx).total

    def render(self, slide, data: StaircaseSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, ctx)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"staircase: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        elif ctx.fill_hint and bbox.h > plan.total:
            # taller stairs when given a whole zone (funnel convention)
            grow = min(_STRETCH_CAP,
                       (bbox.h - plan.value_h)
                       / max(1, plan.total - plan.value_h))
            plan = self._plan(data, ctx, scale=grow)
        n = len(data.steps)
        hi = data.highlight_index if data.highlight_index is not None \
            else n - 1
        if not 0 <= hi < n:
            ctx.report.warn(f"staircase: highlight_index {hi} out of range "
                            f"for {n} steps; using last")
            hi = n - 1
        family = ctx.font("body")
        gap = theme.spacing(_GAP_MULT)
        step_w = (bbox.w - (n - 1) * gap) // n
        base_y = bbox.y + plan.total
        pad = theme.spacing(0.3)

        for i, step in enumerate(data.steps):
            h = plan.step_h(i)
            x = bbox.x + i * (step_w + gap)
            band = BBox(x, base_y - h, step_w, h)
            fill = _HI_FILL if i == hi else _FILL
            s = add_shape(slide, band, theme, shape="rect", fill_role=fill)
            inside = h >= _INSIDE_MIN_H
            ink = "inverse_ink" if inside else "ink"
            fit = fit_text(
                [Span(sp.text, bold=True, italic=sp.italic, color_role=ink)
                 for sp in parse_rich(step.label, base_color_role=ink)],
                BBox(0, 0, max(1, step_w - 2 * pad), _PROBE_H), family,
                max_size=ctx.size("small"), min_size=_MIN_LABEL, max_lines=3,
                measurer=ctx.measurer)
            if fit.truncated:
                ctx.report.truncated(f"staircase: {step.label[:40]!r}")
            if inside:
                tf = make_text_frame(s, align="center", anchor="top")
                tf.margin_top = pad
                write_fit_result(tf, fit, theme, family=family,
                                 align="center", default_color_role=ink)
            else:
                # short first steps: label ABOVE the step, in the headroom
                # the taller stairs to the right leave free
                lbox = add_text_box(
                    slide, BBox(x, band.y - fit.height_emu
                                - theme.spacing(0.2), step_w,
                                fit.height_emu), align="center")
                write_fit_result(lbox.text_frame, fit, theme, family=family,
                                 align="center", default_color_role="ink")
            if step.value:
                vy = band.y - plan.value_h if inside else \
                    band.y - fit.height_emu - theme.spacing(0.2) \
                    - plan.value_h
                vbox = add_text_box(
                    slide, BBox(x, max(bbox.y, vy), step_w,
                                max(1, plan.value_h
                                    - theme.spacing(0.2))),
                    align="center")
                write_spans_paragraph(
                    vbox.text_frame, [Span(step.value, bold=True)],
                    ctx.size("small"), theme, family=family, align="center",
                    default_color_role="ink")
        return plan.total

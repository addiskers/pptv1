"""funnel — top-down conversion funnel of centered narrowing bands.

Reference look: the market-sizing / pipeline slide — stacked primary bands
tapering toward the bottom, the final (payoff) stage flipped to accent, each
stage's value hung just off the band's right edge, short dashed connectors
tying each band to the next.

measure(): band height is one bold 'small' line + spacing(0.6) padding
(min 0.45in); total = n bands + spacing(0.35) gaps — pure arithmetic shared
with render() via _plan. render(): one centered rect per band (width =
frac_i * bbox.w; fracs default to a linear 1.0 -> 0.35 taper), label fit to
a single line inside the band; the value goes right of the band edge when
the measured span fits inside bbox, else right-aligned inside the band in
inverse ink.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape, add_vline
from ..core.pptx_text import (add_text_box, make_text_frame, write_fit_result,
                              write_spans_paragraph)
from ..core.units import inch, to_inch
from ..schema.components import FunnelSpec
from .base import Component, RenderContext, register

_END_FRAC = 0.35      # default taper: linear 1.0 -> 0.35 across stages
_FRAC_MIN = 0.25      # explicit fracs clamp range
_FRAC_MAX = 1.0
_PAD_MULT = 0.6       # band vertical padding + label inset each side
_GAP_MULT = 0.35      # gap between bands (the dashed connector lives here)
_VAL_GAP_MULT = 0.3   # gap between band right edge and outside value
_MIN_BAND_H = inch(0.45)
_MIN_LABEL = 7.5      # shrink floor for the single-line label
_PROBE_H = 10_000_000  # max_lines drives the fit; probe never clips height
_LABEL_ROLE = "inverse_ink"
_FILL_ROLE = "primary"
_LAST_FILL_ROLE = "accent"  # the conversion payoff stage


@dataclass(frozen=True)
class _Plan:
    band_ws: tuple[int, ...]
    band_h: int
    gap: int
    total: int


@register("funnel")
class Funnel(Component):
    spec_model = FunnelSpec

    # -- shared planning (side-effect free) --------------------------------

    def _fracs(self, data: FunnelSpec) -> list[float]:
        n = len(data.stages)
        if data.fracs is not None and len(data.fracs) == n:
            return [min(_FRAC_MAX, max(_FRAC_MIN, f)) for f in data.fracs]
        step = (_FRAC_MAX - _END_FRAC) / max(1, n - 1)
        return [_FRAC_MAX - step * i for i in range(n)]

    def _plan(self, data: FunnelSpec, width: int, ctx: RenderContext) -> _Plan:
        line_h = ctx.measurer.line_height_emu(
            [Span("Hg", bold=True)], ctx.font("body"), ctx.size("small"))
        band_h = max(line_h + ctx.theme.spacing(_PAD_MULT), _MIN_BAND_H)
        gap = ctx.theme.spacing(_GAP_MULT)
        band_ws = tuple(round(width * f) for f in self._fracs(data))
        n = len(data.stages)
        return _Plan(band_ws, band_h, gap, n * band_h + (n - 1) * gap)

    # -- contract -----------------------------------------------------------

    def measure(self, data: FunnelSpec, width: int, ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: FunnelSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        plan = self._plan(data, bbox.w, ctx)
        n = len(data.stages)
        if data.fracs is not None and len(data.fracs) != n:
            ctx.report.warn(
                f"funnel: {len(data.fracs)} fracs for {n} stages; using "
                "default taper")
        band_h = plan.band_h
        if plan.total > bbox.h:
            ctx.report.warn(
                f"funnel: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        elif ctx.fill_hint and bbox.h > plan.total:
            # flex: taller bands, capped growth
            avail = (bbox.h - (n - 1) * plan.gap) // n
            band_h = min(avail, round(plan.band_h * 1.5))

        theme = ctx.theme
        family = ctx.font("body")
        pad = theme.spacing(_PAD_MULT)
        center_x = bbox.x + bbox.w // 2
        y = bbox.y
        for i, (stage, bw) in enumerate(zip(data.stages, plan.band_ws)):
            band = BBox(bbox.x + (bbox.w - bw) // 2, y, bw, band_h)
            fill = _LAST_FILL_ROLE if i == n - 1 else _FILL_ROLE
            shape = add_shape(slide, band, theme, shape="rect",
                              fill_role=fill)
            fit = fit_text(
                [Span(stage.label, bold=True, color_role=_LABEL_ROLE)],
                BBox(0, 0, max(0, bw - 2 * pad), _PROBE_H), family,
                max_size=ctx.size("small"), min_size=_MIN_LABEL,
                max_lines=1, measurer=ctx.measurer)
            if fit.truncated:
                ctx.report.truncated(f"funnel stage label: {stage.label!r}")
            tf = make_text_frame(shape, align="center", anchor="middle")
            write_fit_result(tf, fit, theme, family=family, align="center",
                             default_color_role=_LABEL_ROLE)
            self._render_value(slide, stage.value, band, bbox, ctx)
            if i < n - 1:
                add_vline(slide, center_x, band.bottom, plan.gap, theme,
                          role="ink_muted", weight_pt=0.75, dash="dash")
            y += band_h + plan.gap
        return n * band_h + (n - 1) * plan.gap

    # -- value placement ------------------------------------------------------

    def _render_value(self, slide, value: str, band: BBox, bbox: BBox,
                      ctx: RenderContext) -> None:
        family = ctx.font("body")
        size = ctx.size("small")
        span = Span(value, bold=True)
        vw = ctx.measurer.span_width_emu(span, family, size)
        vx = band.right + ctx.theme.spacing(_VAL_GAP_MULT)
        if vx + vw <= bbox.right:
            box = add_text_box(slide, BBox(vx, band.y, bbox.right - vx,
                                           band.h), anchor="middle")
            write_spans_paragraph(box.text_frame, [span], size, ctx.theme,
                                  family=family, default_color_role="ink")
            return
        # no room outside: right-align inside the band in inverse ink
        pad = ctx.theme.spacing(_PAD_MULT)
        if vw > band.w - 2 * pad:
            ctx.report.warn(
                f"funnel: value {value!r} fits neither beside nor inside its "
                "band; may overflow")
        box = add_text_box(slide, band.inset(left=pad, right=pad),
                           align="right", anchor="middle")
        write_spans_paragraph(box.text_frame,
                              [Span(value, bold=True,
                                    color_role=_LABEL_ROLE)],
                              size, ctx.theme, family=family, align="right",
                              default_color_role=_LABEL_ROLE)

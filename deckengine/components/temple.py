"""temple — goal roof on capability pillars (the strategy-house form).

Trapezoid roof carries the goal (primary_dark, inverse ink); 2-5 pillar
rects carry capability labels (surface_alt, wrapped up to 4 lines);
optional foundation band underneath. highlight_index accents one pillar.

measure(): roof + pillars + foundation arithmetic shared via _plan.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import make_text_frame, write_fit_result
from ..core.units import inch, to_inch
from ..schema.components import TempleSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_ROOF_H = inch(0.62)
_PILLAR_H_MIN = inch(1.15)
_FOUND_H = inch(0.42)
_GAP = inch(0.06)          # roof/pillars/foundation seams
_PILLAR_GAP_MULT = 0.35    # horizontal gap between pillars
_PAD_MULT = 0.3
_MIN_LABEL = 7.0
_PROBE_H = 10_000_000


@dataclass(frozen=True)
class _Plan:
    roof_fit: FitResult
    pillar_fits: tuple[FitResult, ...]
    found_fit: FitResult | None
    pillar_h: int
    total: int


@register("temple")
class Temple(Component):
    spec_model = TempleSpec

    def _plan(self, data: TempleSpec, width: int,
              ctx: RenderContext) -> _Plan:
        theme = ctx.theme
        family = ctx.font("body")
        pad = theme.spacing(_PAD_MULT)
        n = len(data.pillars)
        gap = theme.spacing(_PILLAR_GAP_MULT)
        pillar_w = (width - (n - 1) * gap) // n
        roof_fit = fit_text(
            [Span(s.text, bold=True, italic=s.italic,
                  color_role="inverse_ink")
             for s in parse_rich(data.goal, base_color_role="inverse_ink")],
            BBox(0, 0, round(width * 0.7), _PROBE_H), family,
            max_size=ctx.size("small"), min_size=_MIN_LABEL, max_lines=2,
            measurer=ctx.measurer)
        pillar_fits = tuple(
            fit_text([Span(s.text, bold=True, italic=s.italic,
                           color_role="ink")
                      for s in parse_rich(p, base_color_role="ink")],
                     BBox(0, 0, max(1, pillar_w - 2 * pad), _PROBE_H),
                     family, max_size=ctx.size("small"),
                     min_size=_MIN_LABEL, max_lines=4,
                     measurer=ctx.measurer)
            for p in data.pillars)
        pillar_h = max(_PILLAR_H_MIN,
                       max(f.height_emu for f in pillar_fits) + 2 * pad)
        found_fit = None
        total = _ROOF_H + _GAP + pillar_h
        if data.foundation:
            found_fit = fit_text(
                [Span(s.text, bold=True, italic=s.italic,
                      color_role="inverse_ink")
                 for s in parse_rich(data.foundation,
                                     base_color_role="inverse_ink")],
                BBox(0, 0, round(width * 0.9), _PROBE_H), family,
                max_size=ctx.size("small"), min_size=_MIN_LABEL,
                max_lines=1, measurer=ctx.measurer)
            total += _GAP + _FOUND_H
        return _Plan(roof_fit, pillar_fits, found_fit, pillar_h, total)

    def measure(self, data: TempleSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: TempleSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w, ctx)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"temple: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        n = len(data.pillars)
        hi = data.highlight_index
        if hi is not None and not 0 <= hi < n:
            ctx.report.warn(f"temple: highlight_index {hi} out of range "
                            f"for {n} pillars; ignoring")
            hi = None
        family = ctx.font("body")
        pad = theme.spacing(_PAD_MULT)

        roof = BBox(bbox.x, bbox.y, bbox.w, _ROOF_H)
        rs = add_shape(slide, roof, theme, shape="trapezoid",
                       fill_role="primary_dark")
        try:
            rs.adjustments[0] = 0.18
        except (IndexError, ValueError):
            pass
        rtf = make_text_frame(rs, align="center", anchor="middle")
        write_fit_result(rtf, plan.roof_fit, theme, family=family,
                         align="center", default_color_role="inverse_ink")
        if plan.roof_fit.truncated:
            ctx.report.truncated(f"temple goal: {data.goal[:40]!r}")

        gap = theme.spacing(_PILLAR_GAP_MULT)
        pillar_w = (bbox.w - (n - 1) * gap) // n
        py = roof.bottom + _GAP
        for i, (p, fit) in enumerate(zip(data.pillars, plan.pillar_fits)):
            x = bbox.x + i * (pillar_w + gap)
            fill = "accent" if i == hi else "surface_alt"
            ink = "inverse_ink" if i == hi else "ink"
            ps = add_shape(slide, BBox(x, py, pillar_w, plan.pillar_h),
                           theme, shape="rect", fill_role=fill,
                           line_role="grid", line_w_pt=0.75)
            ptf = make_text_frame(ps, align="center", anchor="middle")
            ptf.margin_left = pad
            ptf.margin_right = pad
            write_fit_result(ptf, fit, theme, family=family, align="center",
                             default_color_role=ink)
            if fit.truncated:
                ctx.report.truncated(f"temple pillar: {p[:40]!r}")

        if plan.found_fit is not None:
            fy = py + plan.pillar_h + _GAP
            fs = add_shape(slide, BBox(bbox.x, fy, bbox.w, _FOUND_H),
                           theme, shape="rect", fill_role="primary")
            ftf = make_text_frame(fs, align="center", anchor="middle")
            write_fit_result(ftf, plan.found_fit, theme, family=family,
                             align="center",
                             default_color_role="inverse_ink")
        return plan.total

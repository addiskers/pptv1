"""pyramid — tiered hierarchy/segmentation triangle (apex first).

Each tier is a symmetric trapezoid (the apex a triangle) whose widths
grow linearly, so the stack reads as one continuous pyramid. Labels sit
inside tiers wide enough to hold them, else to the RIGHT with the values
column (funnel convention). highlight_index accents one tier; default
keeps all tiers primary.

measure(): n * tier_h + (n-1) * gap — pure arithmetic shared with
render() (same _plan), parity by construction.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, make_text_frame, \
    write_fit_result, write_spans_paragraph
from ..core.units import inch, to_inch
from ..schema.components import PyramidSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_GAP_MULT = 0.15
_PAD_MULT = 0.6
_MIN_TIER_H = inch(0.42)
_MIN_LABEL = 7.0
_WIDTH_FRAC = 0.62     # pyramid width share; the rest is the value rail
_APEX_FRAC = 0.22      # apex tier's bottom width as a share of full width
_INSIDE_MIN = 0.34     # tiers narrower than this fraction label outside
_PROBE_H = 10_000_000
_FILL = "primary"
_HI_FILL = "accent"


@dataclass(frozen=True)
class _Plan:
    tier_h: int
    gap: int
    total: int
    widths: tuple[int, ...]   # bottom width per tier, apex first


@register("pyramid")
class Pyramid(Component):
    spec_model = PyramidSpec

    def _plan(self, data: PyramidSpec, width: int,
              ctx: RenderContext) -> _Plan:
        line_h = ctx.measurer.line_height_emu(
            [Span("Hg", bold=True)], ctx.font("body"), ctx.size("small"))
        tier_h = max(line_h + ctx.theme.spacing(_PAD_MULT), _MIN_TIER_H)
        gap = ctx.theme.spacing(_GAP_MULT)
        n = len(data.tiers)
        pyr_w = round(width * _WIDTH_FRAC)
        step = (1.0 - _APEX_FRAC) / max(1, n - 1)
        fracs = [_APEX_FRAC + step * i for i in range(n)]
        if data.inverted:
            fracs = list(reversed(fracs))
        widths = tuple(round(pyr_w * f) for f in fracs)
        return _Plan(tier_h, gap, n * tier_h + (n - 1) * gap, widths)

    def measure(self, data: PyramidSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: PyramidSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w, ctx)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"pyramid: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        n = len(data.tiers)
        hi = data.highlight_index
        if hi is not None and not 0 <= hi < n:
            ctx.report.warn(f"pyramid: highlight_index {hi} out of range "
                            f"for {n} tiers; ignoring")
            hi = None
        family = ctx.font("body")
        pyr_w = round(bbox.w * _WIDTH_FRAC)
        center_x = bbox.x + pyr_w // 2
        rail_x = bbox.x + pyr_w + theme.spacing(0.5)
        rail_w = max(1, bbox.right - rail_x)
        pad = theme.spacing(0.4)

        y = bbox.y
        for i, (tier, bw) in enumerate(zip(data.tiers, plan.widths)):
            band = BBox(center_x - bw // 2, y, bw, plan.tier_h)
            fill = _HI_FILL if i == hi else _FILL
            apex = (i == 0 and not data.inverted) or \
                   (i == n - 1 and data.inverted)
            if apex:
                s = add_shape(slide, band, theme, shape="triangle",
                              fill_role=fill)
            else:
                # symmetric trapezoid: adj = side inset / width so the top
                # edge meets the tier above's bottom edge
                prev = plan.widths[i - 1] if not data.inverted \
                    else plan.widths[i + 1] if i + 1 < n else bw
                top_w = min(prev, bw)
                s = add_shape(slide, band, theme, shape="trapezoid",
                              fill_role=fill)
                try:
                    s.adjustments[0] = max(
                        0.0, min(0.5, (bw - top_w) / (2 * bw)))
                except (IndexError, ValueError):
                    pass
            inside = bw >= bbox.w * _INSIDE_MIN and not apex
            spans = parse_rich(tier.label,
                               base_color_role="inverse_ink" if inside
                               else "ink")
            if inside:
                fit = fit_text([Span(sp.text, bold=True,
                                     color_role="inverse_ink",
                                     italic=sp.italic) for sp in spans],
                               BBox(0, 0, max(1, top_w if not apex else bw)
                                    - 2 * pad if not apex else bw,
                                    _PROBE_H),
                               family, max_size=ctx.size("small"),
                               min_size=_MIN_LABEL, max_lines=1,
                               measurer=ctx.measurer)
                if fit.truncated:
                    ctx.report.truncated(f"pyramid tier: {tier.label[:40]!r}")
                tf = make_text_frame(s, align="center", anchor="middle")
                write_fit_result(tf, fit, theme, family=family,
                                 align="center",
                                 default_color_role="inverse_ink")
            else:
                # narrow tier: ONE rail box holding label + value as two
                # stacked paragraphs (separate boxes collided)
                fit = fit_text([Span(sp.text, bold=True, italic=sp.italic,
                                     color_role="ink") for sp in spans],
                               BBox(0, 0, max(1, rail_w), _PROBE_H),
                               family, max_size=ctx.size("small"),
                               min_size=_MIN_LABEL, max_lines=1,
                               measurer=ctx.measurer)
                box = add_text_box(slide,
                                   BBox(rail_x, y, rail_w, plan.tier_h),
                                   anchor="middle")
                write_fit_result(box.text_frame, fit, theme, family=family,
                                 default_color_role="ink")
                if tier.value:
                    write_spans_paragraph(
                        box.text_frame,
                        [Span(tier.value, color_role="ink_muted")],
                        ctx.size("micro"), theme, family=family,
                        default_color_role="ink_muted",
                        paragraph=box.text_frame.add_paragraph())
            if tier.value and inside:
                vbox = add_text_box(slide,
                                    BBox(rail_x, y, rail_w, plan.tier_h),
                                    anchor="middle")
                write_spans_paragraph(
                    vbox.text_frame, [Span(tier.value, bold=True)],
                    ctx.size("small"), theme, family=family,
                    default_color_role="ink")
            y += plan.tier_h + plan.gap
        return plan.total

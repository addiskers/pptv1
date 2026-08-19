"""hub_spoke — center hub + 3-8 radiating labeled nodes.

Census: 7 primary + 5 secondary uses in the big-firm corpus (ecosystem /
capability / partner wheels). The hub is an accent-less primary circle;
spokes are rounded label chips placed on an ellipse around it, each tied
to the hub by a thin ray drawn UNDER the chips. highlight_index accents
one chip.

Geometry is a pure function of (width, n, chip_h): chips sit at evenly
spaced angles starting at 12 o'clock; the ellipse radii derive from the
width and the fixed component height, so measure() == render() by
construction. Chip labels fit to <=2 lines; sub-lines are micro.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_line, add_shape
from ..core.pptx_text import make_text_frame, write_fit_result, \
    write_spans_paragraph
from ..core.units import inch, to_inch
from ..schema.components import HubSpokeSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_HUB_D = inch(1.5)          # hub circle diameter
_CHIP_W_FRAC = 0.24         # chip width as a share of component width
_CHIP_W_MAX = inch(2.1)
_MIN_LABEL = 7.0
_PROBE_H = 10_000_000
_FILL = "surface_alt"
_HI_FILL = "accent"
_HUB_FILL = "primary_dark"


@dataclass(frozen=True)
class _Plan:
    chip_w: int
    chip_h: int
    total: int
    rx: int              # ellipse x-radius (to chip centers)
    ry: int              # ellipse y-radius


@register("hub_spoke")
class HubSpoke(Component):
    spec_model = HubSpokeSpec

    def _plan(self, data: HubSpokeSpec, width: int,
              ctx: RenderContext) -> _Plan:
        line_h = ctx.measurer.line_height_emu(
            [Span("Hg", bold=True)], ctx.font("body"), ctx.size("small"))
        micro_h = ctx.measurer.line_height_emu(
            [Span("Hg")], ctx.font("body"), ctx.size("micro"))
        has_sub = any(s.sub for s in data.spokes)
        chip_h = (2 * line_h + (micro_h if has_sub else 0)
                  + ctx.theme.spacing(0.5))
        chip_w = min(round(width * _CHIP_W_FRAC), _CHIP_W_MAX)
        # ellipse sized so chips at 12/6 o'clock define the total height
        ry = _HUB_D // 2 + chip_h // 2 + ctx.theme.spacing(1.2)
        rx = max(ry, width // 2 - chip_w // 2 - ctx.theme.spacing(0.3))
        total = 2 * ry + chip_h
        return _Plan(chip_w, chip_h, total, rx, ry)

    def measure(self, data: HubSpokeSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: HubSpokeSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w, ctx)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"hub_spoke: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        n = len(data.spokes)
        hi = data.highlight_index
        if hi is not None and not 0 <= hi < n:
            ctx.report.warn(f"hub_spoke: highlight_index {hi} out of range "
                            f"for {n} spokes; ignoring")
            hi = None
        family = ctx.font("body")
        cx = bbox.x + bbox.w // 2
        cy = bbox.y + plan.total // 2

        # chip centers on the ellipse, starting at 12 o'clock
        centers = []
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            centers.append((cx + round(plan.rx * math.cos(ang)),
                            cy + round(plan.ry * math.sin(ang))))

        # rays first so chips and the hub draw over them
        for px, py in centers:
            add_line(slide, cx, cy, px, py, theme, role="grid",
                     weight_pt=1.0)

        # hub circle + label
        hub = BBox(cx - _HUB_D // 2, cy - _HUB_D // 2, _HUB_D, _HUB_D)
        s = add_shape(slide, hub, theme, shape="oval", fill_role=_HUB_FILL)
        hub_fit = fit_text(parse_rich(data.hub,
                                      base_color_role="inverse_ink"),
                           BBox(0, 0, round(_HUB_D * 0.72), _PROBE_H),
                           family, max_size=ctx.size("small"),
                           min_size=_MIN_LABEL, max_lines=3,
                           measurer=ctx.measurer)
        if hub_fit.truncated:
            ctx.report.truncated(f"hub_spoke hub: {data.hub[:40]!r}")
        tf = make_text_frame(s, align="center", anchor="middle")
        write_fit_result(tf, hub_fit, theme, family=family, align="center",
                         default_color_role="inverse_ink")

        # spoke chips
        for i, (spoke, (px, py)) in enumerate(zip(data.spokes, centers)):
            chip = BBox(px - plan.chip_w // 2, py - plan.chip_h // 2,
                        plan.chip_w, plan.chip_h)
            fill = _HI_FILL if i == hi else _FILL
            ink = "inverse_ink" if i == hi else "ink"
            cs = add_shape(slide, chip, theme, shape="rounded",
                           fill_role=fill, corner_radius=0.25,
                           line_role="grid", line_w_pt=0.75)
            pad = theme.spacing(0.3)
            fit = fit_text(
                [Span(sp.text, bold=True, italic=sp.italic, color_role=ink)
                 for sp in parse_rich(spoke.label, base_color_role=ink)],
                BBox(0, 0, max(1, plan.chip_w - 2 * pad), _PROBE_H),
                family, max_size=ctx.size("small"), min_size=_MIN_LABEL,
                max_lines=2, measurer=ctx.measurer)
            if fit.truncated:
                ctx.report.truncated(f"hub_spoke: {spoke.label[:40]!r}")
            ctf = make_text_frame(cs, align="center", anchor="middle")
            write_fit_result(ctf, fit, theme, family=family, align="center",
                             default_color_role=ink)
            if spoke.sub:
                sub_ink = "inverse_ink" if i == hi else "ink_muted"
                write_spans_paragraph(
                    ctf, [Span(spoke.sub, color_role=sub_ink)],
                    ctx.size("micro"), theme, family=family, align="center",
                    default_color_role=sub_ink,
                    paragraph=ctf.add_paragraph())
        return plan.total

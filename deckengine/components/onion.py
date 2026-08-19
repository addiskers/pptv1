"""onion — concentric layers, core -> periphery (canon: onion).

Nested ovals bottom-aligned (the consulting half-onion look reads better
than centered rings for labels): innermost core in primary_dark with its
label inside (inverse ink); outer layers ramp surface_alt -> primary
soft; every non-core label sits on a RIGHT rail with a leader line into
its ring band — inner rings are too thin for text. highlight_index
accents one layer's ring.

measure(): D (largest oval) — the rail rides within the same height.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_line, add_shape
from ..core.pptx_text import add_text_box, make_text_frame, \
    write_fit_result
from ..core.units import inch, to_inch
from ..schema.components import OnionSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_D_MAX = inch(3.4)
_D_FRAC = 0.44             # largest oval width share of component width
_CORE_FRAC = 0.34          # core diameter as a share of the largest
_MIN_LABEL = 7.0
_PROBE_H = 10_000_000


@dataclass(frozen=True)
class _Plan:
    d: int
    total: int


@register("onion")
class Onion(Component):
    spec_model = OnionSpec

    def _plan(self, data: OnionSpec, width: int) -> _Plan:
        d = min(round(width * _D_FRAC), _D_MAX)
        return _Plan(d, d)

    def measure(self, data: OnionSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width).total

    def render(self, slide, data: OnionSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"onion: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        n = len(data.layers)
        hi = data.highlight_index
        if hi is not None and not 0 <= hi < n:
            ctx.report.warn(f"onion: highlight_index {hi} out of range for "
                            f"{n} layers; ignoring")
            hi = None
        family = ctx.font("body")
        d = plan.d
        cx = bbox.x + d // 2 + theme.spacing(0.5)
        bottom = bbox.y + plan.total

        # layer diameters core-first -> draw outermost first
        step = (1.0 - _CORE_FRAC) / max(1, n - 1)
        diams = [round(d * (_CORE_FRAC + step * i)) for i in range(n)]
        # outer -> inner fills: alternate soft ramp; core = primary_dark
        for i in range(n - 1, -1, -1):
            di = diams[i]
            if i == 0:
                fill_role, fill_hex = "primary_dark", None
            elif i == hi:
                fill_role, fill_hex = None, theme.soft("accent", 0.45)
            else:
                frac = 0.10 + 0.10 * (n - 1 - i)
                fill_role, fill_hex = None, theme.soft("primary", frac)
            oval = BBox(cx - di // 2, bottom - di, di, di)
            kw = {"fill_role": fill_role} if fill_role else \
                {"fill_hex": fill_hex}
            add_shape(slide, oval, theme, shape="oval",
                      line_role="grid", line_w_pt=0.75, **kw)

        # core label inside the innermost oval
        core_d = diams[0]
        core_fit = fit_text(
            [Span(s.text, bold=True, italic=s.italic,
                  color_role="inverse_ink")
             for s in parse_rich(data.layers[0],
                                 base_color_role="inverse_ink")],
            BBox(0, 0, round(core_d * 0.8), _PROBE_H), family,
            max_size=ctx.size("small"), min_size=_MIN_LABEL, max_lines=2,
            measurer=ctx.measurer)
        if core_fit.truncated:
            ctx.report.truncated(f"onion core: {data.layers[0][:40]!r}")
        cbox = add_text_box(
            slide, BBox(cx - round(core_d * 0.4),
                        bottom - core_d // 2 - core_fit.height_emu // 2,
                        round(core_d * 0.8), core_fit.height_emu),
            align="center")
        write_fit_result(cbox.text_frame, core_fit, theme, family=family,
                         align="center", default_color_role="inverse_ink")

        # right rail labels + leader lines for the outer layers
        rail_x = cx + d // 2 + theme.spacing(1.4)
        rail_w = max(1, bbox.right - rail_x)
        for i in range(1, n):
            di, prev = diams[i], diams[i - 1]
            # anchor: middle of ring band i, on the upper arc centerline
            band_y = bottom - prev - (di - prev) // 2
            ink = "accent" if i == hi else "ink"
            fit = fit_text(
                [Span(s.text, bold=True, italic=s.italic, color_role=ink)
                 for s in parse_rich(data.layers[i], base_color_role=ink)],
                BBox(0, 0, rail_w, _PROBE_H), family,
                max_size=ctx.size("small"), min_size=_MIN_LABEL,
                max_lines=1, measurer=ctx.measurer)
            if fit.truncated:
                ctx.report.truncated(f"onion layer: {data.layers[i][:40]!r}")
            add_line(slide, cx + theme.spacing(0.3), band_y,
                     rail_x - theme.spacing(0.3),
                     band_y, theme, role="ink_muted", weight_pt=0.75,
                     dash="dash")
            box = add_text_box(
                slide, BBox(rail_x, band_y - fit.height_emu // 2, rail_w,
                            fit.height_emu))
            write_fit_result(box.text_frame, fit, theme, family=family,
                             default_color_role=ink)
        return plan.total

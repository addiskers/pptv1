"""badge_chip — small rounded-rect pill with a short code in white bold micro text.

Fill comes from theme.badge_palette[code]; unknown codes fall back to the
'ink_muted' role and log a BuildReport warning. Fixed height (one micro line
plus spacing(0.15) padding top and bottom); width hugs the text plus
spacing(0.5), capped at the bbox width.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import Span
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import make_text_frame, write_spans_paragraph
from ..core.units import to_pt
from ..schema.components import BadgeChipSpec
from .base import Component, RenderContext, register

_CORNER_RADIUS = 0.5   # full pill
_PAD_V_MULT = 0.15     # spacing multiple, applied top AND bottom
_PAD_W_MULT = 0.5      # spacing multiple added to text width (total)


@register("badge_chip")
class BadgeChip(Component):
    spec_model = BadgeChipSpec

    def _line_h(self, ctx: RenderContext) -> int:
        return ctx.measurer.line_height_emu(
            [Span("Ag", bold=True)], ctx.font("body"), ctx.size("micro"))

    def measure(self, data: BadgeChipSpec, width: int, ctx: RenderContext) -> int:
        return self._line_h(ctx) + 2 * ctx.theme.spacing(_PAD_V_MULT)

    def render(self, slide, data: BadgeChipSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        line_h = self._line_h(ctx)
        height = line_h + 2 * ctx.theme.spacing(_PAD_V_MULT)
        family = ctx.font("body")
        size = ctx.size("micro")

        span = Span(data.code, bold=True, color_role="inverse_ink")
        text_w = ctx.measurer.span_width_emu(span, family, size)
        chip_w = min(bbox.w, text_w + ctx.theme.spacing(_PAD_W_MULT))
        chip = BBox(bbox.x, bbox.y, chip_w, height)

        fill_hex = ctx.theme.badge_palette.get(data.code)
        if fill_hex is not None:
            s = add_shape(slide, chip, ctx.theme, shape="rounded",
                          fill_hex=fill_hex, corner_radius=_CORNER_RADIUS)
        else:
            ctx.report.warn(
                f"badge_chip: code {data.code!r} not in theme badge_palette")
            s = add_shape(slide, chip, ctx.theme, shape="rounded",
                          fill_role="ink_muted", corner_radius=_CORNER_RADIUS)

        tf = make_text_frame(s, align="center", anchor="middle")
        write_spans_paragraph(tf, [span], size, ctx.theme, family=family,
                              align="center", line_spacing_pt=to_pt(line_h),
                              default_color_role="inverse_ink")
        return height

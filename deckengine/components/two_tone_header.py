"""two_tone_header — split header band: primary label left, alt-surface right.

The band splits at left_frac: the left rect ('primary' fill) carries data.left
in bold small inverse-ink, centered middle; the right rect ('surface_alt')
carries data.right in small 'ink', left-aligned middle with a spacing(0.5)
left inset. Band height is one small line plus spacing(0.5), growing to two
lines when either side wraps at its width (fit_text max_lines=2; the taller
side wins).
"""
from __future__ import annotations

from dataclasses import replace

from ..core.bbox import BBox
from ..core.fit_text import FitResult, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, make_text_frame, write_fit_result
from ..schema.components import TwoToneHeaderSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_PROBE_H = 10_000_000   # generous probe: fit decides its own natural height
_SMALL_MIN = 7.5
_PAD_MULT = 0.5         # vertical padding on top of the taller side's text
_INSET_MULT = 0.5       # left inset for the right cell's text
_MAX_LINES = 2


@register("two_tone_header")
class TwoToneHeader(Component):
    spec_model = TwoToneHeaderSpec

    # -- pure layout math (shared by measure and render) --------------------

    def _fits(self, data: TwoToneHeaderSpec, width: int,
              ctx: RenderContext) -> tuple[FitResult, FitResult, int, int]:
        left_w = round(width * data.left_frac)
        right_w = max(0, width - left_w)
        inset = ctx.theme.spacing(_INSET_MULT)
        left_spans = [replace(s, bold=True) for s in
                      parse_rich(data.left, base_color_role="inverse_ink")]
        left = fit_text(left_spans, BBox(0, 0, max(1, left_w), _PROBE_H),
                        ctx.font("body"), max_size=ctx.size("small"),
                        min_size=_SMALL_MIN, max_lines=_MAX_LINES,
                        measurer=ctx.measurer)
        right = fit_text(parse_rich(data.right, base_color_role="ink"),
                         BBox(0, 0, max(1, right_w - inset), _PROBE_H),
                         ctx.font("body"), max_size=ctx.size("small"),
                         min_size=_SMALL_MIN, max_lines=_MAX_LINES,
                         measurer=ctx.measurer)
        return left, right, left_w, right_w

    def _band_h(self, left: FitResult, right: FitResult,
                ctx: RenderContext) -> int:
        return (max(left.height_emu, right.height_emu)
                + ctx.theme.spacing(_PAD_MULT))

    # -- contract ------------------------------------------------------------

    def measure(self, data: TwoToneHeaderSpec, width: int,
                ctx: RenderContext) -> int:
        left, right, _, _ = self._fits(data, width, ctx)
        return self._band_h(left, right, ctx)

    def render(self, slide, data: TwoToneHeaderSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        family = ctx.font("body")
        left, right, left_w, right_w = self._fits(data, bbox.w, ctx)
        band_h = self._band_h(left, right, ctx)
        if left.truncated:
            ctx.report.truncated(f"two_tone_header left: {data.left[:40]!r}")
        if right.truncated:
            ctx.report.truncated(f"two_tone_header right: {data.right[:40]!r}")

        # left cell: primary fill, bold inverse-ink label centered middle
        left_rect = BBox(bbox.x, bbox.y, left_w, band_h)
        s = add_shape(slide, left_rect, theme, shape="rect",
                      fill_role="primary")
        tf = make_text_frame(s, align="center", anchor="middle")
        write_fit_result(tf, left, theme, family=family, align="center",
                         default_color_role="inverse_ink")

        # right cell: alt surface, small ink text left-aligned middle w/ inset
        right_rect = BBox(bbox.x + left_w, bbox.y, right_w, band_h)
        add_shape(slide, right_rect, theme, shape="rect",
                  fill_role="surface_alt")
        inset = theme.spacing(_INSET_MULT)
        text_box = add_text_box(
            slide, BBox(right_rect.x + inset, right_rect.y,
                        max(1, right_w - inset), band_h),
            align="left", anchor="middle")
        write_fit_result(text_box.text_frame, right, theme, family=family,
                         align="left", default_color_role="ink")

        if band_h > bbox.h:
            ctx.report.warn("two_tone_header: band taller than provided bbox")
        return band_h

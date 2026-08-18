"""numbered_block — 1A/1B-style marker: accent number circle + titled text stack.

An accent-filled circle (diameter = min(0.42in, two 'small' lines)) holds
data.number in bold small inverse-ink, centered middle. To its right, after a
spacing(0.5) gap, sits a text column: title at 'h2' in 'primary' (rich,
bold-capable via fit_text spans), then an optional small 'ink' body
spacing(0.25) below. Block height = max(circle diameter, text stack height);
circle and stack are mutually vertically centered.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, make_text_frame, write_fit_result, \
    write_spans_paragraph
from ..core.units import inch, to_pt
from ..schema.components import NumberedBlockSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_PROBE_H = 10_000_000       # generous probe: fit decides its own natural height
_MAX_DIAMETER = inch(0.42)
_TITLE_MIN = 11.0
_BODY_MIN = 7.5
_CIRCLE_GAP_MULT = 0.5      # gap between circle and text column
_TITLE_BODY_GAP_MULT = 0.25


@register("numbered_block")
class NumberedBlock(Component):
    spec_model = NumberedBlockSpec

    # -- pure layout math (shared by measure and render) --------------------

    def _diameter(self, ctx: RenderContext) -> int:
        two_lines = 2 * ctx.measurer.line_height_emu(
            [Span("Ag", bold=True)], ctx.font("body"), ctx.size("small"))
        return min(_MAX_DIAMETER, two_lines)

    def _fits(self, data: NumberedBlockSpec, width: int,
              ctx: RenderContext,
              max_h: int = _PROBE_H) -> tuple[int, FitResult, FitResult | None]:
        d = self._diameter(ctx)
        gap = ctx.theme.spacing(_CIRCLE_GAP_MULT)
        col_w = max(1, width - d - gap)
        title = fit_text(parse_rich(data.title, base_color_role="primary"),
                         BBox(0, 0, col_w, max_h), ctx.font("body"),
                         max_size=ctx.size("h2"),
                         min_size=_TITLE_MIN, measurer=ctx.measurer)
        body = None
        if data.body is not None:
            body_h = (max_h if max_h == _PROBE_H else
                      max(1, max_h - title.height_emu
                          - ctx.theme.spacing(_TITLE_BODY_GAP_MULT)))
            body = fit_text(parse_rich(data.body, base_color_role="ink"),
                            BBox(0, 0, col_w, body_h), ctx.font("body"),
                            max_size=ctx.size("small"),
                            min_size=_BODY_MIN, measurer=ctx.measurer)
        return d, title, body

    def _stack_h(self, title: FitResult, body: FitResult | None,
                 ctx: RenderContext) -> int:
        h = title.height_emu
        if body is not None:
            h += ctx.theme.spacing(_TITLE_BODY_GAP_MULT) + body.height_emu
        return h

    # -- contract ------------------------------------------------------------

    def measure(self, data: NumberedBlockSpec, width: int,
                ctx: RenderContext) -> int:
        d, title, body = self._fits(data, width, ctx)
        return max(d, self._stack_h(title, body, ctx))

    def render(self, slide, data: NumberedBlockSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        family = ctx.font("body")
        d, title, body = self._fits(data, bbox.w, ctx)
        stack_h = self._stack_h(title, body, ctx)
        total = max(d, stack_h)
        if total > bbox.h and bbox.h >= d:
            # a canvas cell can be shorter than the natural stack: refit the
            # text INTO the cell (shrink -> ellipsize, reported) — the block
            # never paints over the neighbour below
            d, title, body = self._fits(data, bbox.w, ctx, max_h=bbox.h)
            stack_h = self._stack_h(title, body, ctx)
            total = max(d, min(stack_h, bbox.h))

        # number circle, vertically centered against the text stack
        circle = BBox(bbox.x, bbox.y + (total - d) // 2, d, d)
        s = add_shape(slide, circle, theme, shape="oval", fill_role="accent")
        num_span = Span(data.number, bold=True, color_role="inverse_ink")
        num_line_h = ctx.measurer.line_height_emu([num_span], family,
                                                  ctx.size("small"))
        tf = make_text_frame(s, align="center", anchor="middle")
        write_spans_paragraph(tf, [num_span], ctx.size("small"), theme,
                              family=family, align="center",
                              line_spacing_pt=to_pt(num_line_h),
                              default_color_role="inverse_ink")

        # text column to the right, itself centered against the circle
        gap = theme.spacing(_CIRCLE_GAP_MULT)
        col_x = bbox.x + d + gap
        col_w = max(1, bbox.w - d - gap)
        y = bbox.y + (total - stack_h) // 2
        if title.truncated:
            ctx.report.truncated(f"numbered_block title: {data.title[:40]!r}")
        box = add_text_box(slide, BBox(col_x, y, col_w, title.height_emu))
        write_fit_result(box.text_frame, title, theme, family=family,
                         default_color_role="primary")
        y += title.height_emu
        if body is not None:
            y += theme.spacing(_TITLE_BODY_GAP_MULT)
            if body.truncated:
                ctx.report.truncated(f"numbered_block body: {data.body[:40]!r}")
            box = add_text_box(slide, BBox(col_x, y, col_w, body.height_emu))
            write_fit_result(box.text_frame, body, theme, family=family,
                             default_color_role="ink")

        if total > bbox.h:
            ctx.report.warn("numbered_block: block taller than provided bbox")
        return total

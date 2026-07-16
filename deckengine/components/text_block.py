"""text_block — reference component implementation.

Pattern every component follows:
  measure(): pure fit_text math, no side effects
  render(): same math, then draw via core.pptx_text; return identical height
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import fit_text
from ..core.pptx_text import add_text_box, write_fit_result
from ..schema.components import TextBlockSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_MIN_SIZES = {"title": 14.0, "h2": 11.0, "body": 8.0, "small": 7.5, "micro": 6.5}


@register("text_block")
class TextBlock(Component):
    spec_model = TextBlockSpec

    def _fit(self, data: TextBlockSpec, width: int, ctx: RenderContext):
        spans = parse_rich(data.text, base_color_role=data.color_role)
        size = ctx.size(data.size_role)
        # generous height: fit decides real height; bbox.h only caps truncation
        probe = BBox(0, 0, width, 10_000_000)
        return fit_text(spans, probe, ctx.font(data.font_role),
                        max_size=size, min_size=_MIN_SIZES[data.size_role],
                        max_lines=data.max_lines, measurer=ctx.measurer)

    def measure(self, data: TextBlockSpec, width: int, ctx: RenderContext) -> int:
        return self._fit(data, width, ctx).height_emu

    def render(self, slide, data: TextBlockSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        spans = parse_rich(data.text, base_color_role=data.color_role)
        size = ctx.size(data.size_role)
        fit = fit_text(spans, bbox, ctx.font(data.font_role),
                       max_size=size, min_size=_MIN_SIZES[data.size_role],
                       max_lines=data.max_lines, measurer=ctx.measurer)
        if fit.truncated:
            ctx.report.truncated(f"text_block: {data.text[:40]!r}")
        box = add_text_box(slide, bbox.with_height(fit.height_emu),
                           align=data.align)
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font(data.font_role), align=data.align,
                         default_color_role=data.color_role)
        return fit.height_emu

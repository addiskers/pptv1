"""footnote_strip — sources/caveats line at the slide foot.

All notes joined with ' | ' into one micro-size, muted, wrapped block.
Notes are plain strings (no rich markup), so we build a single Span directly.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_text import add_text_box, write_fit_result
from ..schema.components import FootnoteStripSpec
from .base import Component, RenderContext, register

_MIN_SIZE = 6.0
_SEPARATOR = " | "


@register("footnote_strip")
class FootnoteStrip(Component):
    spec_model = FootnoteStripSpec

    def _fit(self, data: FootnoteStripSpec, box: BBox,
             ctx: RenderContext) -> FitResult:
        spans = [Span(_SEPARATOR.join(data.notes), color_role="ink_muted")]
        return fit_text(spans, box, ctx.font("body"),
                        max_size=ctx.size("micro"), min_size=_MIN_SIZE,
                        measurer=ctx.measurer)

    def measure(self, data: FootnoteStripSpec, width: int,
                ctx: RenderContext) -> int:
        return self._fit(data, BBox(0, 0, width, 10_000_000), ctx).height_emu

    def render(self, slide, data: FootnoteStripSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        fit = self._fit(data, bbox, ctx)
        if fit.truncated:
            ctx.report.truncated(
                f"footnote_strip: {_SEPARATOR.join(data.notes)[:40]!r}")
        box = add_text_box(slide, bbox.with_height(fit.height_emu))
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("body"),
                         default_color_role="ink_muted")
        return fit.height_emu

"""highlight_box — filled key-takeaway panel with optional accent bar.

A flat themed rectangle (no outline) with spacing(0.8) inner padding: a title
at h2 size over an optional small body, spacing(0.4) apart. When accent_bar is
set, a spacing(0.35)-wide accent-colored bar sits flush against the panel's
left edge at full panel height.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, write_fit_result
from ..schema.components import HighlightBoxSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_TITLE_MIN = 11.0
_BODY_MIN = 7.5


@register("highlight_box")
class HighlightBox(Component):
    spec_model = HighlightBoxSpec

    def _fits(self, data: HighlightBoxSpec, width: int, avail_h: int,
              ctx: RenderContext) -> tuple[FitResult, FitResult | None]:
        """Fit title (and body if present) inside the padded panel; pure math."""
        pad = ctx.theme.spacing(0.8)
        gap = ctx.theme.spacing(0.4)
        inner_w = max(1, width - 2 * pad)
        inner_h = max(0, avail_h - 2 * pad)
        title = fit_text(parse_rich(data.title, base_color_role="ink"),
                         BBox(0, 0, inner_w, inner_h), ctx.font("body"),
                         max_size=ctx.size("h2"), min_size=_TITLE_MIN,
                         measurer=ctx.measurer)
        body = None
        if data.body is not None:
            body_h = max(0, inner_h - title.height_emu - gap)
            body = fit_text(parse_rich(data.body, base_color_role="ink"),
                            BBox(0, 0, inner_w, body_h), ctx.font("body"),
                            max_size=ctx.size("small"), min_size=_BODY_MIN,
                            measurer=ctx.measurer)
        return title, body

    def _height(self, title: FitResult, body: FitResult | None,
                ctx: RenderContext) -> int:
        h = 2 * ctx.theme.spacing(0.8) + title.height_emu
        if body is not None:
            h += ctx.theme.spacing(0.4) + body.height_emu
        return h

    def measure(self, data: HighlightBoxSpec, width: int,
                ctx: RenderContext) -> int:
        title, body = self._fits(data, width, 10_000_000, ctx)
        return self._height(title, body, ctx)

    def render(self, slide, data: HighlightBoxSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        pad = ctx.theme.spacing(0.8)
        gap = ctx.theme.spacing(0.4)
        title, body = self._fits(data, bbox.w, bbox.h, ctx)
        if title.truncated:
            ctx.report.truncated(f"highlight_box title: {data.title[:40]!r}")
        if body is not None and body.truncated:
            ctx.report.truncated(f"highlight_box body: {data.body[:40]!r}")
        total = self._height(title, body, ctx)

        panel = bbox.with_height(total)
        add_shape(slide, panel, ctx.theme, fill_role=data.fill_role)
        if data.accent_bar:
            add_shape(slide, BBox(panel.x, panel.y, ctx.theme.spacing(0.35),
                                  panel.h), ctx.theme, fill_role="accent")

        inner_w = max(1, bbox.w - 2 * pad)
        title_box = add_text_box(slide, BBox(bbox.x + pad, bbox.y + pad,
                                             inner_w, title.height_emu))
        write_fit_result(title_box.text_frame, title, ctx.theme,
                         family=ctx.font("body"), default_color_role="ink")
        if body is not None:
            body_y = bbox.y + pad + title.height_emu + gap
            body_box = add_text_box(slide, BBox(bbox.x + pad, body_y,
                                                inner_w, body.height_emu))
            write_fit_result(body_box.text_frame, body, ctx.theme,
                             family=ctx.font("body"), default_color_role="ink")
        return total

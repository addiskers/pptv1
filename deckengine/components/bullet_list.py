"""bullet_list — consulting bullets with bold-lead-in support.

Per item: level indent (level * spacing(2)), a fixed glyph column of width
spacing(1.2) holding the bullet dot, then rich text fitted into the remaining
width via fit_text. Vertical rhythm is a spacing(0.35) gap between items
(no gap after the last).
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_text import add_text_box, write_fit_result, write_spans_paragraph
from ..schema.components import BulletItemSpec, BulletListSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_MIN_SIZES = {"body": 8.0, "small": 7.5}
_GLYPH = "•"  # bullet dot


@register("bullet_list")
class BulletList(Component):
    spec_model = BulletListSpec

    def _item_fit(self, item: BulletItemSpec, data: BulletListSpec, width: int,
                  avail_h: int, ctx: RenderContext) -> tuple[int, int, FitResult]:
        """(indent_emu, text_width_emu, fit) for one item; pure math."""
        indent = item.level * ctx.theme.spacing(2)
        glyph_w = ctx.theme.spacing(1.2)
        text_w = max(1, width - indent - glyph_w)
        spans = parse_rich(item.text)
        fit = fit_text(spans, BBox(0, 0, text_w, avail_h), ctx.font("body"),
                       max_size=ctx.size(data.size_role),
                       min_size=_MIN_SIZES[data.size_role],
                       measurer=ctx.measurer)
        return indent, text_w, fit

    def measure(self, data: BulletListSpec, width: int, ctx: RenderContext) -> int:
        gap = ctx.theme.spacing(0.35)
        total = 0
        for i, item in enumerate(data.items):
            _, _, fit = self._item_fit(item, data, width, 10_000_000, ctx)
            total += fit.height_emu
            if i < len(data.items) - 1:
                total += gap
        return total

    def render(self, slide, data: BulletListSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        gap = ctx.theme.spacing(0.35)
        if ctx.fill_hint and len(data.items) > 1:
            # flex: distribute items across the zone (capped so it never gets airy)
            natural = self.measure(data, bbox.w, ctx)
            surplus = max(0, bbox.h - natural)
            gap += min(surplus // (len(data.items) - 1),
                       ctx.theme.spacing(2.2))
        glyph_w = ctx.theme.spacing(1.2)
        glyph_size = ctx.size(data.size_role)
        cursor = bbox.y
        for i, item in enumerate(data.items):
            avail = max(0, bbox.bottom - cursor)
            indent, text_w, fit = self._item_fit(item, data, bbox.w, avail, ctx)
            if fit.truncated:
                ctx.report.truncated(f"bullet_list item {i}: {item.text[:40]!r}")
            first_line_h = fit.lines[0].height_emu if fit.lines else fit.height_emu
            glyph_box = add_text_box(
                slide, BBox(bbox.x + indent, cursor, glyph_w, first_line_h))
            write_spans_paragraph(glyph_box.text_frame,
                                  [Span(_GLYPH, color_role="primary")],
                                  glyph_size, ctx.theme, family=ctx.font("body"),
                                  line_spacing_pt=fit.line_spacing_pt)
            text_box = add_text_box(
                slide, BBox(bbox.x + indent + glyph_w, cursor, text_w,
                            fit.height_emu))
            write_fit_result(text_box.text_frame, fit, ctx.theme,
                             family=ctx.font("body"))
            cursor += fit.height_emu
            if i < len(data.items) - 1:
                cursor += gap
        return cursor - bbox.y

"""icon_tile_row — banded stat rows with a dark icon tile at the left.

Reference: the Gates impact slide's right rail — a small dark rounded tile
holding a white icon, a big stat, then a description, each row on an alternating
surface band. Distinct from icon_stat_row (which uses a circle and no band).
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_icon, add_shape
from ..core.pptx_text import (add_text_box, make_text_frame, write_fit_result,
                              write_spans_paragraph)
from ..core.icons import ICON_NAMES
from ..core.units import inch
from ..schema.components import IconTileRowSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_ROW_MIN = inch(0.6)


@register("icon_tile_row")
class IconTileRow(Component):
    spec_model = IconTileRowSpec

    def _row_h(self, ctx: RenderContext) -> int:
        line = ctx.measurer.line_height_emu([Span("Xg", bold=True)],
                                            ctx.font("body"), ctx.size("stat"))
        return max(_ROW_MIN, line + ctx.theme.spacing(1.0))

    def measure(self, data: IconTileRowSpec, width: int,
                ctx: RenderContext) -> int:
        rh = self._row_h(ctx)
        gap = ctx.theme.spacing(0.3)
        return len(data.tiles) * rh + gap * (len(data.tiles) - 1)

    def render(self, slide, data: IconTileRowSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        rh = self._row_h(ctx)
        gap = theme.spacing(0.3)
        pad = theme.spacing(0.5)
        y = bbox.y
        for i, tile in enumerate(data.tiles):
            band = BBox(bbox.x, y, bbox.w, rh)
            if data.banded:
                add_shape(slide, band, theme,
                          fill_role="surface" if i % 2 == 0 else "surface_alt")
            # dark icon tile
            tile_d = rh - theme.spacing(0.5)
            tb = BBox(bbox.x + pad, y + (rh - tile_d) // 2, tile_d, tile_d)
            add_shape(slide, tb, theme, shape="rounded", fill_role="primary_dark",
                      corner_radius=0.18)
            if tile.icon in ICON_NAMES:
                add_icon(slide, tb.inset(round(tile_d * 0.24)), tile.icon, theme,
                         color_role="inverse_ink")
            # stat + description on one baseline
            cursor = tb.right + theme.spacing(0.6)
            stat_spans = [Span(s.text, bold=True, superscript=s.superscript,
                               highlight_role=s.highlight_role)
                          for s in parse_rich(tile.stat)]
            # measure stat width to place the description after it
            sw = sum(ctx.measurer.span_width_emu(s, ctx.font("body"),
                                                 ctx.size("stat"))
                     for s in stat_spans) + theme.spacing(0.5)
            sb = add_text_box(slide, BBox(cursor, y, sw, rh), anchor="middle")
            write_spans_paragraph(sb.text_frame, stat_spans, ctx.size("stat"),
                                  theme, family=ctx.font("body"),
                                  default_color_role="ink")
            desc_x = cursor + sw
            desc_w = max(inch(0.5), bbox.right - desc_x - pad)
            dfit = fit_text(parse_rich(tile.text),
                            BBox(0, 0, desc_w, rh), ctx.font("body"),
                            max_size=ctx.size("small"), min_size=8,
                            max_lines=2, measurer=ctx.measurer)
            db = add_text_box(slide, BBox(desc_x, y + (rh - dfit.height_emu) // 2,
                                          desc_w, dfit.height_emu))
            write_fit_result(db.text_frame, dfit, theme, family=ctx.font("body"),
                             default_color_role="ink")
            y += rh + gap
        return len(data.tiles) * rh + gap * (len(data.tiles) - 1)

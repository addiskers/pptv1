"""legend_row — horizontal row of [badge pill + label] pairs.

Each item is a small rounded pill (badge-palette fill, white bold micro code)
followed by a micro label. Items lay left-to-right at measured widths on a
single row; overflow beyond the bbox is warned about but still rendered (v1
accepts the clip risk).
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import Span
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, write_spans_paragraph, make_text_frame
from ..core.units import to_inch, to_pt
from ..schema.components import LegendItemSpec, LegendRowSpec
from .base import Component, RenderContext, register

_PILL_PAD_MULT = 0.4   # horizontal padding inside the pill, each side
_PILL_GAP_MULT = 0.3   # gap between a pill and its label
_ITEM_GAP_MULT = 0.8   # gap between items
_LABEL_BUFFER_MULT = 0.2  # slack on label boxes so PowerPoint can never wrap


@register("legend_row")
class LegendRow(Component):
    spec_model = LegendRowSpec

    # -- shared math (side-effect free) -----------------------------------

    def _line_h(self, ctx: RenderContext) -> int:
        """One 'micro' line pitch; pill text is bold, so take the max face."""
        return ctx.measurer.line_height_emu(
            [Span("Xg"), Span("Xg", bold=True)],
            ctx.font("body"), ctx.size("micro"))

    def _pill_h(self, ctx: RenderContext) -> int:
        return self._line_h(ctx) + ctx.theme.spacing(0.2)

    def _item_widths(self, item: LegendItemSpec,
                     ctx: RenderContext) -> tuple[int, int]:
        """(pill_w, label_w) in EMU."""
        family = ctx.font("body")
        size = ctx.size("micro")
        pill_w = (ctx.measurer.span_width_emu(Span(item.code, bold=True),
                                              family, size)
                  + 2 * ctx.theme.spacing(_PILL_PAD_MULT))
        label_w = ctx.measurer.span_width_emu(Span(item.label), family, size)
        return pill_w, label_w

    # -- contract ----------------------------------------------------------

    def measure(self, data: LegendRowSpec, width: int, ctx: RenderContext) -> int:
        return self._pill_h(ctx)

    def render(self, slide, data: LegendRowSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        family = ctx.font("body")
        size = ctx.size("micro")
        pill_h = self._pill_h(ctx)
        spacing_pt = to_pt(self._line_h(ctx))
        gap_in = ctx.theme.spacing(_PILL_GAP_MULT)
        gap_item = ctx.theme.spacing(_ITEM_GAP_MULT)

        widths = [self._item_widths(item, ctx) for item in data.items]
        total = (sum(pw + gap_in + lw for pw, lw in widths)
                 + gap_item * (len(data.items) - 1))
        if total > bbox.w:
            ctx.report.warn(
                f"legend_row: content width {to_inch(total):.2f}in exceeds "
                f"bbox width {to_inch(bbox.w):.2f}in; rendering anyway (may clip)")

        # unknown codes get DISTINCT colors from a deterministic cycle —
        # an all-navy legend defeats the point of a legend
        _CYCLE = ("primary", "accent", "positive", "primary_dark", "negative",
                  "ink_muted")
        x = bbox.x
        for i, (item, (pill_w, label_w)) in enumerate(zip(data.items, widths)):
            fill_role = item.code
            try:
                ctx.theme.color(fill_role)
            except KeyError:
                fill_role = _CYCLE[i % len(_CYCLE)]
            pill = add_shape(slide, BBox(x, bbox.y, pill_w, pill_h), ctx.theme,
                             shape="rounded", fill_role=fill_role,
                             corner_radius=0.5)
            tf = make_text_frame(pill, align="center", anchor="middle")
            write_spans_paragraph(
                tf, [Span(item.code, bold=True, color_role="inverse_ink")],
                size, ctx.theme, family=family, align="center",
                line_spacing_pt=spacing_pt, default_color_role="inverse_ink")
            x += pill_w + gap_in

            # single-line label known to fit its measured width (+ slack so
            # PowerPoint can never wrap earlier than we measured)
            label_box = add_text_box(
                slide,
                BBox(x, bbox.y, label_w + ctx.theme.spacing(_LABEL_BUFFER_MULT),
                     pill_h),
                align="left", anchor="middle")
            write_spans_paragraph(
                label_box.text_frame, [Span(item.label, color_role="ink")],
                size, ctx.theme, family=family, align="left",
                line_spacing_pt=spacing_pt, default_color_role="ink")
            x += label_w + gap_item
        return pill_h

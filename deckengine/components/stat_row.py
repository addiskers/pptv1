"""stat_row — N stats side by side: small centered label over a bold stat value,
optionally finished with a thin centered rule under the value.

Layout per stat cell (equal columns via bbox.cols):
    label   (size 'small', ink, centered, single line)
    gap     spacing(0.25)
    value   (size 'stat', bold, ink, centered, single line)
    gap     spacing(0.15)          } only when any stat underlines
    rule    1.0pt 'ink_muted', ~60% of cell width, centered
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import Span
from ..core.pptx_shapes import add_hline
from ..core.pptx_text import add_text_box, write_spans_paragraph
from ..core.units import pt, to_pt
from ..schema.components import StatRowSpec
from .base import Component, RenderContext, register

_RULE_W_PT = 1.0     # underline stroke weight
_RULE_FRAC = 0.60    # underline width as a fraction of the stat cell width


@register("stat_row")
class StatRow(Component):
    spec_model = StatRowSpec

    def _stack(self, data: StatRowSpec, ctx: RenderContext) -> tuple[int, int, int, int, int]:
        """(label_h, gap1, value_h, gap2, rule_h) — identical in measure/render."""
        family = ctx.font("body")
        label_h = ctx.measurer.line_height_emu(
            [Span("Ag")], family, ctx.size("small"))
        value_h = ctx.measurer.line_height_emu(
            [Span("Ag", bold=True)], family, ctx.size("stat"))
        gap1 = ctx.theme.spacing(0.25)
        underlined = any(s.underline for s in data.stats)
        gap2 = ctx.theme.spacing(0.15) if underlined else 0
        rule_h = pt(_RULE_W_PT) if underlined else 0
        return label_h, gap1, value_h, gap2, rule_h

    def measure(self, data: StatRowSpec, width: int, ctx: RenderContext) -> int:
        label_h, gap1, value_h, gap2, rule_h = self._stack(data, ctx)
        return label_h + gap1 + value_h + gap2 + rule_h

    def render(self, slide, data: StatRowSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        label_h, gap1, value_h, gap2, rule_h = self._stack(data, ctx)
        family = ctx.font("body")
        size_small = ctx.size("small")
        size_stat = ctx.size("stat")

        for stat, cell in zip(data.stats, bbox.cols(len(data.stats))):
            label_span = Span(stat.label, color_role="ink")
            value_span = Span(stat.value, bold=True, color_role="ink")
            for span, size in ((label_span, size_small), (value_span, size_stat)):
                if ctx.measurer.span_width_emu(span, family, size) > cell.w:
                    ctx.report.warn(
                        f"stat_row: {span.text!r} wider than its stat cell")

            y = cell.y
            lbl = add_text_box(slide, BBox(cell.x, y, cell.w, label_h),
                               align="center")
            write_spans_paragraph(lbl.text_frame, [label_span], size_small,
                                  ctx.theme, family=family, align="center",
                                  line_spacing_pt=to_pt(label_h),
                                  default_color_role="ink")
            y += label_h + gap1

            val = add_text_box(slide, BBox(cell.x, y, cell.w, value_h),
                               align="center")
            write_spans_paragraph(val.text_frame, [value_span], size_stat,
                                  ctx.theme, family=family, align="center",
                                  line_spacing_pt=to_pt(value_h),
                                  default_color_role="ink")
            y += value_h

            if stat.underline:
                y += gap2
                rule_w = round(cell.w * _RULE_FRAC)
                rule_x = cell.x + (cell.w - rule_w) // 2
                # centre the stroke inside the rule_h band so it stays in-bbox
                add_hline(slide, rule_x, y + rule_h // 2, rule_w, ctx.theme,
                          role="ink_muted", weight_pt=_RULE_W_PT)

        return label_h + gap1 + value_h + gap2 + rule_h

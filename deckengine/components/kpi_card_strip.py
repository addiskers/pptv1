"""kpi_card_strip — row of N equal dark stat cards.

Reference look: the '$2.2B leveraged / 60+ innovations / 150+ companies' band —
filled rects, centered inverse-ink stat title over a micro body line.

measure(): pure fit_text math on per-card inner widths; card height is the max
content height across cards plus padding (min 0.9in). render(): same math, one
add_shape rect per card with a middle-anchored centered text frame.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import make_text_frame, write_fit_result, write_spans_paragraph
from ..core.units import inch, to_pt
from ..schema.components import KpiCardStripSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_PROBE_H = 10_000_000  # fit decides real height; probe never truncates
_MIN_STAT = 10.0
_MIN_MICRO = 6.5
_TEXT_ROLE = "inverse_ink"
_MIN_CARD_H = inch(0.9)


@register("kpi_card_strip")
class KpiCardStrip(Component):
    spec_model = KpiCardStripSpec

    # -- shared planning (side-effect free) --------------------------------

    def _plan(self, data: KpiCardStripSpec, width: int,
              ctx: RenderContext) -> tuple[list[tuple[FitResult, FitResult]], int]:
        """Per-card (title_fit, body_fit) plus the uniform card height."""
        gap = ctx.theme.spacing(0.5)
        pad = ctx.theme.spacing(0.6)
        title_body_gap = ctx.theme.spacing(0.3)
        cols = BBox(0, 0, width, _PROBE_H).cols(len(data.cards), gap=gap)
        fits: list[tuple[FitResult, FitResult]] = []
        content_h = 0
        for card, col in zip(data.cards, cols):
            inner = BBox(0, 0, max(0, col.w - 2 * pad), _PROBE_H)
            title_fit = fit_text(
                parse_rich(card.title, base_color_role=_TEXT_ROLE),
                inner, ctx.font("body"), max_size=ctx.size("stat"),
                min_size=_MIN_STAT, measurer=ctx.measurer)
            body_fit = fit_text(
                parse_rich(card.body, base_color_role=_TEXT_ROLE),
                inner, ctx.font("body"), max_size=ctx.size("micro"),
                min_size=_MIN_MICRO, measurer=ctx.measurer)
            fits.append((title_fit, body_fit))
            content_h = max(content_h, title_fit.height_emu + title_body_gap
                            + body_fit.height_emu)
        card_h = max(content_h + 2 * pad, _MIN_CARD_H)
        return fits, card_h

    # -- contract -----------------------------------------------------------

    def measure(self, data: KpiCardStripSpec, width: int,
                ctx: RenderContext) -> int:
        _, card_h = self._plan(data, width, ctx)
        return card_h

    def render(self, slide, data: KpiCardStripSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        fits, card_h = self._plan(data, bbox.w, ctx)
        if card_h > bbox.h:
            ctx.report.warn(
                f"kpi_card_strip: card height {card_h} exceeds bbox height {bbox.h}")
        elif ctx.fill_hint and bbox.h > card_h:
            # flex: taller cards (text stays middle-anchored), capped growth
            card_h = min(bbox.h, round(card_h * 1.5))
        gap = ctx.theme.spacing(0.5)
        gap_pt = to_pt(ctx.theme.spacing(0.3))
        family = ctx.font("body")
        cols = bbox.cols(len(data.cards), gap=gap)
        for (title_fit, body_fit), col in zip(fits, cols):
            card = add_shape(slide, col.with_height(card_h), ctx.theme,
                             shape="rect", fill_role=data.fill_role, shadow=True)
            tf = make_text_frame(card, align="center", anchor="middle")
            write_fit_result(tf, title_fit, ctx.theme, family=family,
                             align="center", default_color_role=_TEXT_ROLE)
            # exact-height spacer paragraph between title and body
            write_spans_paragraph(tf, [Span("")], body_fit.size_pt, ctx.theme,
                                  family=family, align="center",
                                  line_spacing_pt=gap_pt,
                                  default_color_role=_TEXT_ROLE,
                                  paragraph=tf.add_paragraph())
            for line in body_fit.lines:
                write_spans_paragraph(tf, line.spans, body_fit.size_pt,
                                      ctx.theme, family=family, align="center",
                                      line_spacing_pt=body_fit.line_spacing_pt,
                                      default_color_role=_TEXT_ROLE,
                                      paragraph=tf.add_paragraph())
        return card_h

"""kpi_card_strip — row of N equal dark stat cards.

Reference look: the '$2.2B leveraged / 60+ innovations / 150+ companies' band —
filled rects, centered inverse-ink stat title over a micro body line.

A card may instead hold a micro-viz (progress_pill or donut_stat) under a
small caption title — the reference FMD tile. The viz spec is copied with
inverse=True and its donut hole matched to the card fill, so nested
components stay surface-agnostic.

measure(): pure fit_text math on per-card inner widths; card height is the max
content height across cards plus padding (min 0.9in). render(): same math, one
add_shape rect per card; text cards use a middle-anchored frame, viz cards
place a caption then delegate to the nested component.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import (add_text_box, make_text_frame, write_fit_result,
                              write_spans_paragraph)
from ..core.units import inch, to_pt
from ..schema.components import KpiCardSpec, KpiCardStripSpec
from ..schema.rich import parse_rich, plain
from .base import Component, RenderContext, get_component, register

_PROBE_H = 10_000_000  # fit decides real height; probe never truncates
_MIN_STAT = 10.0
_MIN_MICRO = 6.5
_MIN_CAPTION = 7.5
_TEXT_ROLE = "inverse_ink"
_MIN_CARD_H = inch(0.9)


@dataclass(frozen=True)
class _CardPlan:
    title_fit: FitResult
    body_fit: FitResult | None   # None for viz cards and body-less cards
    viz_h: int                   # 0 unless the card holds a viz
    content_h: int


@register("kpi_card_strip")
class KpiCardStrip(Component):
    spec_model = KpiCardStripSpec

    # -- shared planning (side-effect free) --------------------------------

    def _viz_spec(self, card: KpiCardSpec, data: KpiCardStripSpec):
        """Container-adapted copy: inverse text; donut hole matches card fill."""
        upd: dict = {"inverse": True}
        if card.viz.kind == "donut_stat":
            upd["hole_fill_role"] = data.fill_role
        return card.viz.model_copy(update=upd)

    def _plan(self, data: KpiCardStripSpec, width: int,
              ctx: RenderContext) -> tuple[list[_CardPlan], int]:
        gap = ctx.theme.spacing(0.5)
        pad = ctx.theme.spacing(0.6)
        title_body_gap = ctx.theme.spacing(0.3)
        cols = BBox(0, 0, width, _PROBE_H).cols(len(data.cards), gap=gap)
        plans: list[_CardPlan] = []
        card_content = 0
        for card, col in zip(data.cards, cols):
            inner = BBox(0, 0, max(0, col.w - 2 * pad), _PROBE_H)
            if card.viz is not None:
                # caption-sized title over the nested viz
                title_fit = fit_text(
                    parse_rich(card.title, base_color_role=_TEXT_ROLE),
                    inner, ctx.font("body"), max_size=ctx.size("small"),
                    min_size=_MIN_CAPTION, measurer=ctx.measurer)
                viz = self._viz_spec(card, data)
                viz_h = get_component(viz.kind).measure(viz, inner.w, ctx)
                content_h = title_fit.height_emu + title_body_gap + viz_h
                plans.append(_CardPlan(title_fit, None, viz_h, content_h))
            else:
                title_fit = fit_text(
                    parse_rich(card.title, base_color_role=_TEXT_ROLE),
                    inner, ctx.font("body"), max_size=ctx.size("stat"),
                    min_size=_MIN_STAT, measurer=ctx.measurer)
                body_fit = None
                content_h = title_fit.height_emu
                if card.body:
                    body_fit = fit_text(
                        parse_rich(card.body, base_color_role=_TEXT_ROLE),
                        inner, ctx.font("body"), max_size=ctx.size("micro"),
                        min_size=_MIN_MICRO, measurer=ctx.measurer)
                    content_h += title_body_gap + body_fit.height_emu
                plans.append(_CardPlan(title_fit, body_fit, 0, content_h))
            card_content = max(card_content, content_h)
        card_h = max(card_content + 2 * pad, _MIN_CARD_H)
        return plans, card_h

    @staticmethod
    def _blank(data: KpiCardStripSpec) -> bool:
        """Every card blank (no title/body text, no viz): an empty strip of
        dark rects is a bug, not content — measure 0 so the stacker drops it."""
        return all(not plain(c.title).strip()
                   and not plain(c.body or "").strip()
                   and c.viz is None for c in data.cards)

    # -- contract -----------------------------------------------------------

    def measure(self, data: KpiCardStripSpec, width: int,
                ctx: RenderContext) -> int:
        if self._blank(data):
            return 0
        _, card_h = self._plan(data, width, ctx)
        return card_h

    def render(self, slide, data: KpiCardStripSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        if self._blank(data):
            ctx.report.warn("kpi_card_strip: all-blank payload; skipped")
            return 0
        plans, card_h = self._plan(data, bbox.w, ctx)
        if card_h > bbox.h:
            ctx.report.warn(
                f"kpi_card_strip: card height {card_h} exceeds bbox height {bbox.h}")
        elif ctx.fill_hint and bbox.h > card_h:
            # flex: taller cards (content stays centered), capped growth
            card_h = min(bbox.h, round(card_h * 1.5))
        gap = ctx.theme.spacing(0.5)
        pad = ctx.theme.spacing(0.6)
        gap_pt = to_pt(ctx.theme.spacing(0.3))
        title_body_gap = ctx.theme.spacing(0.3)
        family = ctx.font("body")
        cols = bbox.cols(len(data.cards), gap=gap)
        for card, plan, col in zip(data.cards, plans, cols):
            shape = add_shape(slide, col.with_height(card_h), ctx.theme,
                              shape="rect", fill_role=data.fill_role,
                              shadow=True)
            if card.viz is not None:
                inner_w = max(1, col.w - 2 * pad)
                y = col.y + (card_h - plan.content_h) // 2
                tbox = add_text_box(
                    slide, BBox(col.x + pad, y, inner_w,
                                plan.title_fit.height_emu), align="center")
                write_fit_result(tbox.text_frame, plan.title_fit, ctx.theme,
                                 family=family, align="center",
                                 default_color_role=_TEXT_ROLE)
                viz = self._viz_spec(card, data)
                get_component(viz.kind).render(
                    slide, viz,
                    BBox(col.x + pad,
                         y + plan.title_fit.height_emu + title_body_gap,
                         inner_w, plan.viz_h), ctx)
                continue
            tf = make_text_frame(shape, align="center", anchor="middle")
            write_fit_result(tf, plan.title_fit, ctx.theme, family=family,
                             align="center", default_color_role=_TEXT_ROLE)
            if plan.body_fit is None:
                continue
            # exact-height spacer paragraph between title and body
            write_spans_paragraph(tf, [Span("")], plan.body_fit.size_pt,
                                  ctx.theme, family=family, align="center",
                                  line_spacing_pt=gap_pt,
                                  default_color_role=_TEXT_ROLE,
                                  paragraph=tf.add_paragraph())
            for line in plan.body_fit.lines:
                write_spans_paragraph(tf, line.spans, plan.body_fit.size_pt,
                                      ctx.theme, family=family, align="center",
                                      line_spacing_pt=plan.body_fit.line_spacing_pt,
                                      default_color_role=_TEXT_ROLE,
                                      paragraph=tf.add_paragraph())
        return card_h

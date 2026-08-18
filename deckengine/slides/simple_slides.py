"""Assemblers for title, section_divider, bullet_content, exec_summary."""
from __future__ import annotations

from ..components.base import RenderContext
from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_hline, add_shape
from ..core.pptx_text import add_text_box, write_fit_result, write_spans_paragraph
from ..core.units import inch
from ..layout.stacker import item, stack_into
from ..layout.zones import SLIDE
from ..schema.components import (BulletListSpec, SectionHeaderSpec,
                                 TextBlockSpec)
from ..schema.rich import parse_rich
from ..schema.slide_types import (BulletContentSpec, ExecSummarySpec,
                                  SectionDividerSpec, TitleSlideSpec)
from .base import SlideAssembler, register_slide


@register_slide("title")
class TitleSlide(SlideAssembler):
    """The cover, in four compositions (spec.style) so a variant batch
    never opens five decks on the same-looking slide. 'dark_hero' is the
    reference full-bleed dark cover; the others are equally hand-built
    (covers must never break — they stay off the freeform designer)."""

    def assemble(self, slide, spec: TitleSlideSpec, ctx: RenderContext) -> None:
        {"dark_hero": self._dark_hero,
         "split_panel": self._split_panel,
         "light_minimal": self._light_minimal,
         "band_statement": self._band_statement,
         }.get(getattr(spec, "style", "dark_hero"), self._dark_hero)(
            slide, spec, ctx)

    # -- shared fragments ---------------------------------------------------

    def _date(self, slide, spec, ctx, color_role: str) -> None:
        if not spec.date:
            return
        # top-LEFT so the deck logo (drawn top-right by deck_builder) has
        # the corner to itself
        db = add_text_box(slide, BBox(inch(1.1), inch(0.35),
                                      inch(2.8), inch(0.3)), align="left")
        write_spans_paragraph(db.text_frame, [Span(spec.date)],
                              ctx.size("small"), ctx.theme,
                              family=ctx.font("body"), align="left",
                              default_color_role=color_role)

    def _title_block(self, slide, spec, ctx, area: BBox, y: int,
                     color_role: str, max_size: float = 40,
                     min_size: float = 26) -> int:
        """Big serif title + optional subtitle; returns the y below them."""
        title_bb = BBox(area.x, y, area.w, inch(2.2))
        fit = fit_text(parse_rich(spec.title), title_bb, ctx.font("display"),
                       max_size=max_size, min_size=min_size,
                       measurer=ctx.measurer)
        box = add_text_box(slide, title_bb.with_height(fit.height_emu))
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("display"),
                         default_color_role=color_role)
        y = title_bb.y + fit.height_emu + ctx.theme.spacing(1.2)
        if spec.subtitle:
            sub_bb = BBox(area.x, y, area.w, inch(0.9))
            sfit = fit_text(parse_rich(spec.subtitle), sub_bb,
                            ctx.font("body"), max_size=ctx.size("h2"),
                            min_size=11, measurer=ctx.measurer)
            sbox = add_text_box(slide, sub_bb.with_height(sfit.height_emu))
            write_fit_result(sbox.text_frame, sfit, ctx.theme,
                             family=ctx.font("body"),
                             default_color_role=color_role)
            y = sub_bb.y + sfit.height_emu
        return y

    def _org(self, slide, spec, ctx, area: BBox, color_role: str,
             y: int | None = None) -> None:
        if not spec.org:
            return
        ob = add_text_box(slide, BBox(area.x,
                                      SLIDE.h - inch(2.5) if y is None else y,
                                      area.w, inch(0.6)))
        write_spans_paragraph(ob.text_frame, [Span(spec.org)],
                              ctx.size("small"), ctx.theme,
                              family=ctx.font("body"),
                              default_color_role=color_role)

    def _wordmark(self, slide, spec, ctx, size: float = 66) -> None:
        # oversized wordmark bleeding off the bottom edge (the human touch)
        if not spec.wordmark:
            return
        wm = add_text_box(slide, BBox(inch(0.3), SLIDE.h - inch(1.45),
                                      SLIDE.w - inch(0.6), inch(1.6)),
                          anchor="bottom")
        write_spans_paragraph(wm.text_frame,
                              [Span(spec.wordmark, bold=True)], size,
                              ctx.theme, family=ctx.font("display"),
                              default_color_role="accent")

    # -- the four covers ----------------------------------------------------

    def _dark_hero(self, slide, spec, ctx) -> None:
        """Full-bleed dark cover: oversized serif title in cream, an accent
        wordmark bleeding off the bottom edge."""
        add_shape(slide, SLIDE, ctx.theme, fill_role="primary_dark")
        self._date(slide, spec, ctx, "inverse_ink")
        area = SLIDE.inset(left=inch(1.1), right=inch(1.1))
        self._title_block(slide, spec, ctx, area, inch(1.5), "inverse_ink")
        self._org(slide, spec, ctx, area, "inverse_ink")
        self._wordmark(slide, spec, ctx)

    def _split_panel(self, slide, spec, ctx) -> None:
        """Dark title panel on the left 45%, light field right with the
        standfirst riding an accent rule."""
        panel_w = round(SLIDE.w * 0.45)
        add_shape(slide, BBox(0, 0, panel_w, SLIDE.h), ctx.theme,
                  fill_role="primary_dark")
        self._date(slide, spec, ctx, "inverse_ink")
        left = BBox(inch(0.7), 0, panel_w - inch(1.4), SLIDE.h)
        title_bb = BBox(left.x, inch(1.6), left.w, inch(3.4))
        fit = fit_text(parse_rich(spec.title), title_bb, ctx.font("display"),
                       max_size=32, min_size=20, measurer=ctx.measurer)
        box = add_text_box(slide, title_bb.with_height(fit.height_emu))
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("display"),
                         default_color_role="inverse_ink")
        self._org(slide, spec, ctx, left, "inverse_ink")
        # right field: accent rule + subtitle mid-height
        rx = panel_w + inch(0.9)
        rw = SLIDE.w - rx - inch(1.1)
        add_hline(slide, rx, inch(2.9), inch(1.6), ctx.theme, role="accent",
                  weight_pt=3.0)
        if spec.subtitle:
            sub_bb = BBox(rx, inch(3.15), rw, inch(1.4))
            sfit = fit_text(parse_rich(spec.subtitle), sub_bb,
                            ctx.font("body"), max_size=ctx.size("h2"),
                            min_size=11, measurer=ctx.measurer)
            sbox = add_text_box(slide, sub_bb.with_height(sfit.height_emu))
            write_fit_result(sbox.text_frame, sfit, ctx.theme,
                             family=ctx.font("body"),
                             default_color_role="ink")
        if spec.wordmark:
            wm = add_text_box(slide, BBox(rx, SLIDE.h - inch(1.0), rw,
                                          inch(0.6)), anchor="bottom")
            write_spans_paragraph(wm.text_frame,
                                  [Span(spec.wordmark, bold=True)], 20,
                                  ctx.theme, family=ctx.font("display"),
                                  default_color_role="accent")

    def _light_minimal(self, slide, spec, ctx) -> None:
        """Airy light cover: a short accent rule, big ink serif title,
        muted standfirst — restraint as the statement."""
        self._date(slide, spec, ctx, "ink_muted")
        area = SLIDE.inset(left=inch(1.1), right=inch(2.2))
        add_hline(slide, area.x, inch(1.9), inch(1.6), ctx.theme,
                  role="accent", weight_pt=3.0)
        self._title_block(slide, spec, ctx, area, inch(2.25), "ink")
        # org sits low, clear of the deepest possible title+standfirst stack
        self._org(slide, spec, ctx, area, "ink_muted",
                  y=SLIDE.h - inch(1.55))
        if spec.wordmark:
            wm = add_text_box(slide, BBox(area.x, SLIDE.h - inch(1.0),
                                          area.w, inch(0.6)),
                              anchor="bottom")
            write_spans_paragraph(wm.text_frame,
                                  [Span(spec.wordmark, bold=True)], 20,
                                  ctx.theme, family=ctx.font("display"),
                                  default_color_role="accent")

    def _band_statement(self, slide, spec, ctx) -> None:
        """Light cover with a full-width primary band carrying the title —
        the statement runs edge to edge."""
        self._date(slide, spec, ctx, "ink_muted")
        pad = inch(0.55)
        title_w = SLIDE.w - 2 * inch(1.1)
        fit = fit_text(parse_rich(spec.title),
                       BBox(0, 0, title_w, inch(2.2)), ctx.font("display"),
                       max_size=36, min_size=24, measurer=ctx.measurer)
        band_h = fit.height_emu + 2 * pad
        band_y = inch(2.1)
        add_shape(slide, BBox(0, band_y, SLIDE.w, band_h), ctx.theme,
                  fill_role="primary")
        box = add_text_box(slide, BBox(inch(1.1), band_y + pad, title_w,
                                       fit.height_emu))
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("display"),
                         default_color_role="inverse_ink")
        area = SLIDE.inset(left=inch(1.1), right=inch(1.1))
        if spec.subtitle:
            sub_bb = BBox(area.x, band_y + band_h + inch(0.35), area.w,
                          inch(0.9))
            sfit = fit_text(parse_rich(spec.subtitle), sub_bb,
                            ctx.font("body"), max_size=ctx.size("h2"),
                            min_size=11, measurer=ctx.measurer)
            sbox = add_text_box(slide, sub_bb.with_height(sfit.height_emu))
            write_fit_result(sbox.text_frame, sfit, ctx.theme,
                             family=ctx.font("body"),
                             default_color_role="ink_muted")
        # org sits low, clear of the deepest possible band + standfirst
        self._org(slide, spec, ctx, area, "ink_muted",
                  y=SLIDE.h - inch(1.55))
        if spec.wordmark:
            wm = add_text_box(slide, BBox(area.x, SLIDE.h - inch(1.0),
                                          area.w, inch(0.6)),
                              anchor="bottom")
            write_spans_paragraph(wm.text_frame,
                                  [Span(spec.wordmark, bold=True)], 20,
                                  ctx.theme, family=ctx.font("display"),
                                  default_color_role="accent")


@register_slide("section_divider")
class SectionDivider(SlideAssembler):
    """Bold full-bleed colour-block divider (reference style), or a left-bar
    variant when spec.style == 'bar'."""

    def assemble(self, slide, spec: SectionDividerSpec, ctx: RenderContext) -> None:
        bleed = spec.style == "bleed"
        if bleed:
            add_shape(slide, SLIDE, ctx.theme, fill_role="accent")
            title_role = "inverse_ink"
            num_role = "inverse_ink"
            sub_role = "inverse_ink"
            align = "center"
            area = SLIDE.inset(left=inch(1.5), right=inch(1.5))
        else:
            add_shape(slide, BBox(0, 0, inch(0.18), SLIDE.h), ctx.theme,
                      fill_role="primary")
            title_role = "primary"
            num_role = "accent"
            sub_role = "ink_muted"
            align = "left"
            area = SLIDE.inset(left=inch(1.0), right=inch(1.2))

        y = SLIDE.h // 3 if not bleed else inch(2.7)
        if spec.number:
            nb = add_text_box(slide, BBox(area.x, y - inch(0.95), area.w,
                                          inch(0.85)), align=align)
            write_spans_paragraph(nb.text_frame, [Span(spec.number, bold=True)],
                                  40, ctx.theme, family=ctx.font("display"),
                                  align=align, default_color_role=num_role)
        tb = BBox(area.x, y, area.w, inch(1.4))
        fit = fit_text(parse_rich(spec.title), tb, ctx.font("display"),
                       max_size=30, min_size=20, measurer=ctx.measurer)
        box = add_text_box(slide, tb.with_height(fit.height_emu), align=align)
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("display"), align=align,
                         default_color_role=title_role)
        if spec.subtitle:
            sb = BBox(area.x, tb.y + fit.height_emu + ctx.theme.spacing(1),
                      area.w, inch(0.8))
            sfit = fit_text(parse_rich(spec.subtitle), sb, ctx.font("body"),
                            max_size=ctx.size("h2"), min_size=10,
                            measurer=ctx.measurer)
            sbox = add_text_box(slide, sb.with_height(sfit.height_emu),
                                align=align)
            write_fit_result(sbox.text_frame, sfit, ctx.theme,
                             family=ctx.font("body"), align=align,
                             default_color_role=sub_role)


@register_slide("bullet_content")
class BulletContent(SlideAssembler):
    def assemble(self, slide, spec: BulletContentSpec, ctx: RenderContext) -> None:
        z = self.render_title(slide, spec, ctx)
        stack_into(slide, z["body"].inset(top=ctx.theme.spacing(1)), ctx, [
            item("bullet_list", BulletListSpec(items=spec.bullets), flex=1.0)])


@register_slide("exec_summary")
class ExecSummary(SlideAssembler):
    def assemble(self, slide, spec: ExecSummarySpec, ctx: RenderContext) -> None:
        z = self.render_title(slide, spec, ctx)
        body = z["body"].inset(top=ctx.theme.spacing(1))
        items = []
        for i, sec in enumerate(spec.sections):
            items.append(item("text_block", TextBlockSpec(
                text=f"[[primary]]{sec.heading}[[/]]", size_role="h2"),
                gap_before=0.4 if i == 0 else 1.4))
            items.append(item("text_block", TextBlockSpec(
                text=sec.body, size_role="body"), gap_before=0.45))
        stack_into(slide, body, ctx, items)

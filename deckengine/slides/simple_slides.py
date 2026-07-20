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
    """Full-bleed dark cover: oversized serif title in cream, an accent
    wordmark bleeding off the bottom edge — a real cover, not text on white."""

    def assemble(self, slide, spec: TitleSlideSpec, ctx: RenderContext) -> None:
        add_shape(slide, SLIDE, ctx.theme, fill_role="primary_dark")

        if spec.date:
            db = add_text_box(slide, BBox(SLIDE.w - inch(3.2), inch(0.35),
                                          inch(2.8), inch(0.3)), align="right")
            write_spans_paragraph(db.text_frame, [Span(spec.date)],
                                  ctx.size("small"), ctx.theme,
                                  family=ctx.font("body"), align="right",
                                  default_color_role="inverse_ink")

        area = SLIDE.inset(left=inch(1.1), right=inch(1.1))
        title_bb = BBox(area.x, inch(1.5), area.w, inch(2.2))
        fit = fit_text(parse_rich(spec.title), title_bb, ctx.font("display"),
                       max_size=40, min_size=26, measurer=ctx.measurer)
        box = add_text_box(slide, title_bb.with_height(fit.height_emu))
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("display"),
                         default_color_role="inverse_ink")
        y = title_bb.y + fit.height_emu + ctx.theme.spacing(1.2)
        if spec.subtitle:
            sub_bb = BBox(area.x, y, area.w, inch(0.9))
            sfit = fit_text(parse_rich(spec.subtitle), sub_bb, ctx.font("body"),
                            max_size=ctx.size("h2"), min_size=11,
                            measurer=ctx.measurer)
            sbox = add_text_box(slide, sub_bb.with_height(sfit.height_emu))
            write_fit_result(sbox.text_frame, sfit, ctx.theme,
                             family=ctx.font("body"),
                             default_color_role="inverse_ink")

        if spec.org:
            ob = add_text_box(slide, BBox(area.x, SLIDE.h - inch(2.5), area.w,
                                          inch(0.6)))
            write_spans_paragraph(ob.text_frame, [Span(spec.org)],
                                  ctx.size("small"), ctx.theme,
                                  family=ctx.font("body"),
                                  default_color_role="inverse_ink")

        # oversized wordmark bleeding off the bottom edge (the human touch)
        if spec.wordmark:
            wm = add_text_box(slide, BBox(inch(0.3), SLIDE.h - inch(1.45),
                                          SLIDE.w - inch(0.6), inch(1.6)),
                              anchor="bottom")
            write_spans_paragraph(wm.text_frame,
                                  [Span(spec.wordmark, bold=True)], 66, ctx.theme,
                                  family=ctx.font("display"),
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
        z = self.zones()
        stack_into(slide, z["title"], ctx, [
            item("section_header", SectionHeaderSpec(
                title=spec.title, subtitle=spec.subtitle))])
        stack_into(slide, z["body"].inset(top=ctx.theme.spacing(1)), ctx, [
            item("bullet_list", BulletListSpec(items=spec.bullets), flex=1.0)])


@register_slide("exec_summary")
class ExecSummary(SlideAssembler):
    def assemble(self, slide, spec: ExecSummarySpec, ctx: RenderContext) -> None:
        z = self.zones()
        stack_into(slide, z["title"], ctx, [
            item("section_header", SectionHeaderSpec(title=spec.title))])
        body = z["body"].inset(top=ctx.theme.spacing(1))
        items = []
        for i, sec in enumerate(spec.sections):
            items.append(item("text_block", TextBlockSpec(
                text=f"[[primary]]{sec.heading}[[/]]", size_role="h2"),
                gap_before=0.4 if i == 0 else 1.4))
            items.append(item("text_block", TextBlockSpec(
                text=sec.body, size_role="body"), gap_before=0.45))
        stack_into(slide, body, ctx, items)

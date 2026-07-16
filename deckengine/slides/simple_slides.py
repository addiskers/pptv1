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
    def assemble(self, slide, spec: TitleSlideSpec, ctx: RenderContext) -> None:
        band = BBox(0, SLIDE.h // 3, SLIDE.w, inch(0.06))
        add_shape(slide, band, ctx.theme, fill_role="accent")
        area = SLIDE.inset(left=inch(1.0), right=inch(1.0))
        title_bb = BBox(area.x, SLIDE.h // 3 + inch(0.35), area.w, inch(1.6))
        fit = fit_text(parse_rich(spec.title), title_bb, ctx.font("display"),
                       max_size=30, min_size=20, measurer=ctx.measurer)
        box = add_text_box(slide, title_bb.with_height(fit.height_emu))
        write_fit_result(box.text_frame, fit, ctx.theme, family=ctx.font("display"),
                         default_color_role="primary")
        y = title_bb.y + fit.height_emu + ctx.theme.spacing(1.5)
        if spec.subtitle:
            sub_bb = BBox(area.x, y, area.w, inch(0.9))
            sfit = fit_text(parse_rich(spec.subtitle), sub_bb, ctx.font("body"),
                            max_size=ctx.size("h2"), min_size=10,
                            measurer=ctx.measurer)
            sbox = add_text_box(slide, sub_bb.with_height(sfit.height_emu))
            write_fit_result(sbox.text_frame, sfit, ctx.theme,
                             family=ctx.font("body"),
                             default_color_role="ink_muted")
        meta_bits = " | ".join(b for b in (spec.date, spec.org) if b)
        if meta_bits:
            mb = add_text_box(slide, BBox(area.x, SLIDE.h - inch(0.9), area.w,
                                          inch(0.3)))
            write_spans_paragraph(mb.text_frame, [Span(meta_bits)],
                                  ctx.size("small"), ctx.theme,
                                  family=ctx.font("body"),
                                  default_color_role="ink_muted")


@register_slide("section_divider")
class SectionDivider(SlideAssembler):
    def assemble(self, slide, spec: SectionDividerSpec, ctx: RenderContext) -> None:
        add_shape(slide, BBox(0, 0, inch(0.18), SLIDE.h), ctx.theme,
                  fill_role="primary")
        area = SLIDE.inset(left=inch(1.0), right=inch(1.2))
        y = SLIDE.h // 3
        if spec.number:
            nb = add_text_box(slide, BBox(area.x, y - inch(0.9), area.w, inch(0.8)))
            write_spans_paragraph(nb.text_frame, [Span(spec.number, bold=True)],
                                  40, ctx.theme, family=ctx.font("display"),
                                  default_color_role="accent")
        tb = BBox(area.x, y, area.w, inch(1.4))
        fit = fit_text(parse_rich(spec.title), tb, ctx.font("display"),
                       max_size=26, min_size=18, measurer=ctx.measurer)
        box = add_text_box(slide, tb.with_height(fit.height_emu))
        write_fit_result(box.text_frame, fit, ctx.theme,
                         family=ctx.font("display"), default_color_role="primary")
        if spec.subtitle:
            sb = BBox(area.x, tb.y + fit.height_emu + ctx.theme.spacing(1),
                      area.w, inch(0.8))
            sfit = fit_text(parse_rich(spec.subtitle), sb, ctx.font("body"),
                            max_size=ctx.size("h2"), min_size=10,
                            measurer=ctx.measurer)
            sbox = add_text_box(slide, sb.with_height(sfit.height_emu))
            write_fit_result(sbox.text_frame, sfit, ctx.theme,
                             family=ctx.font("body"), default_color_role="ink_muted")


@register_slide("bullet_content")
class BulletContent(SlideAssembler):
    def assemble(self, slide, spec: BulletContentSpec, ctx: RenderContext) -> None:
        z = self.zones()
        stack_into(slide, z["title"], ctx, [
            item("section_header", SectionHeaderSpec(
                title=spec.title, subtitle=spec.subtitle))])
        stack_into(slide, z["body"].inset(top=ctx.theme.spacing(1)), ctx, [
            item("bullet_list", BulletListSpec(items=spec.bullets))])


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

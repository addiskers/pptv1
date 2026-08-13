"""Assemblers for chart_slide, framework_slide, timeline_slide,
strategy_overview (the Gates slide-1 pattern)."""
from __future__ import annotations

from ..components.base import RenderContext, get_component
from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import (add_text_box, make_text_frame,
                              write_fit_result, write_spans_paragraph)
from ..core.units import inch
from ..layout.stacker import item, stack_into
from ..layout.zones import with_sidebar
from ..schema.components import (BulletListSpec, SectionHeaderSpec,
                                 TextBlockSpec)
from ..schema.rich import parse_rich
from ..schema.slide_types import (ChartSlideSpec, FrameworkSlideSpec,
                                  StrategyOverviewSpec, TimelineSlideSpec)
from .base import SlideAssembler, register_slide


def _title(self, slide, spec, ctx, rule=False):
    return self.render_title(slide, spec, ctx, rule=rule)


def _footnote_item(spec):
    return item("text_block", TextBlockSpec(
        text=spec.footnote, size_role="micro", color_role="ink_muted"),
        gap_before=0.6)


@register_slide("chart_slide")
class ChartSlide(SlideAssembler):
    def assemble(self, slide, spec: ChartSlideSpec, ctx: RenderContext) -> None:
        z = _title(self, slide, spec, ctx)
        body = z["body"]
        if spec.insights:
            zones = with_sidebar(body, side_frac=0.28)
            main, side = zones["main"], zones["sidebar"]
            side_items = []
            if spec.insights_heading:
                side_items.append(item("text_block", TextBlockSpec(
                    text=f"**{spec.insights_heading}**", size_role="h2",
                    color_role="primary"), gap_before=0.8))
            side_items.append(item("bullet_list", BulletListSpec(
                items=spec.insights, size_role="small"), gap_before=0.8))
            stack_into(slide, side, ctx, side_items)
        else:
            main = body
        items = [item("native_chart", spec.chart, gap_before=0.8, flex=1.0)]
        if spec.footnote:
            items.append(_footnote_item(spec))
        stack_into(slide, main, ctx, items)


@register_slide("framework_slide")
class FrameworkSlide(SlideAssembler):
    def assemble(self, slide, spec: FrameworkSlideSpec,
                 ctx: RenderContext) -> None:
        z = _title(self, slide, spec, ctx)
        body = z["body"]
        top_items = []
        if spec.pathway:
            top_items.append(item("chevron_pathway", spec.pathway,
                                  gap_before=0.8))
        if top_items:
            consumed = stack_into(slide, body, ctx, top_items)
            _, body = body.take_top(consumed + ctx.theme.spacing(1.2))
        # numbered blocks: 2-column grid when 4+, else stacked
        blocks = [item("numbered_block", b,
                       gap_before=0.0 if i == 0 else 1.0)
                  for i, b in enumerate(spec.blocks)]
        if len(blocks) >= 4:
            half = (len(blocks) + 1) // 2
            left, right = body.split_h(1, 1, gap=ctx.theme.spacing(1.5))
            stack_into(slide, left, ctx, blocks[:half])
            stack_into(slide, right, ctx, blocks[half:])
        else:
            stack_into(slide, body, ctx, blocks)
        if spec.footnote:
            stack_into(slide, BBox(body.x, body.bottom - inch(0.3), body.w,
                                   inch(0.3)), ctx, [_footnote_item(spec)])


@register_slide("timeline_slide")
class TimelineSlide(SlideAssembler):
    def assemble(self, slide, spec: TimelineSlideSpec,
                 ctx: RenderContext) -> None:
        z = _title(self, slide, spec, ctx)
        body = z["body"]
        consumed = stack_into(slide, body, ctx, [
            item("timeline_row", spec.timeline, gap_before=1.0)])
        _, rest = body.take_top(consumed + ctx.theme.spacing(1.5))
        if spec.phases:
            cols = rest.cols(len(spec.phases), gap=ctx.theme.spacing(1.2))
            for col, phase in zip(cols, spec.phases):
                stack_into(slide, col, ctx,
                           [item("numbered_block", phase, gap_before=0.4)])
        if spec.footnote:
            stack_into(slide, BBox(rest.x, rest.bottom - inch(0.3), rest.w,
                                   inch(0.3)), ctx, [_footnote_item(spec)])


@register_slide("strategy_overview")
class StrategyOverview(SlideAssembler):
    """Boss fight: principles rail | dense pipeline table | goals sidebar."""

    def assemble(self, slide, spec: StrategyOverviewSpec,
                 ctx: RenderContext) -> None:
        theme = ctx.theme
        z = _title(self, slide, spec, ctx)
        body = z["body"]
        if spec.legend:
            consumed = stack_into(slide, body, ctx, [
                item("legend_row", spec.legend, gap_before=0.3)],
                record_fill=False)  # strip in a tall zone: not a fill signal
            _, body = body.take_top(consumed + theme.spacing(0.8))
        if spec.footnote:
            foot, body = body.take_bottom(inch(0.32))
        left, center, right = body.split_h(0.20, 0.575, 0.225,
                                           gap=theme.spacing(1.0))

        # left rail: heading box + principles
        stack_into(slide, left, ctx, [
            item("text_block", TextBlockSpec(
                text=f"**{spec.left_heading}**", size_role="h2",
                color_role="primary")),
            item("bullet_list", BulletListSpec(items=spec.principles,
                                               size_role="small"),
                 gap_before=0.8, flex=1.0)])

        # center: optional heading + the pipeline table
        center_items = []
        if spec.table_heading:
            center_items.append(item("text_block", TextBlockSpec(
                text=f"**{spec.table_heading}**", size_role="h2",
                color_role="accent")))
        center_items.append(item("data_table", spec.table,
                                 gap_before=0.6 if spec.table_heading else 0.0,
                                 flex=1.0))
        stack_into(slide, center, ctx, center_items)

        # right sidebar: dark heading, goal boxes joined by down-arrows,
        # optional co-benefits
        self._sidebar(slide, right, spec, ctx)

        if spec.footnote:
            stack_into(slide, foot, ctx, [item("text_block", TextBlockSpec(
                text=spec.footnote, size_role="micro",
                color_role="ink_muted"))])

    def _sidebar(self, slide, rail: BBox, spec: StrategyOverviewSpec,
                 ctx: RenderContext) -> None:
        theme = ctx.theme
        add_shape(slide, rail, theme, fill_role="primary_dark")
        inner = rail.inset(theme.spacing(0.7))
        cursor = inner.y

        head_fit = fit_text(parse_rich(spec.sidebar_heading),
                            BBox(0, 0, inner.w, inch(1)), ctx.font("body"),
                            max_size=ctx.size("small"), min_size=8,
                            measurer=ctx.measurer)
        box = add_text_box(slide, BBox(inner.x, cursor, inner.w,
                                       head_fit.height_emu), align="center")
        for line in head_fit.lines:
            for s in line.spans:
                object.__setattr__(s, "bold", True)
        write_fit_result(box.text_frame, head_fit, theme,
                         family=ctx.font("body"), align="center",
                         default_color_role="inverse_ink")
        cursor += head_fit.height_emu + theme.spacing(1.0)

        arrow_h = theme.spacing(1.1)
        avail = inner.bottom - cursor - arrow_h * (len(spec.goals) - 1)
        if spec.cobenefits:
            # must mirror the render path below exactly, or the last box clips
            cob_h = (theme.spacing(1.0)
                     + (inch(0.28) if spec.cobenefits_heading else 0)
                     + len(spec.cobenefits) * inch(0.52))
            avail -= cob_h
        goal_h = max(inch(0.55), avail // max(1, len(spec.goals)))

        for i, goal in enumerate(spec.goals):
            gb = BBox(inner.x, cursor, inner.w, goal_h)
            s = add_shape(slide, gb, theme, fill_role="bg")
            tf = __import__("deckengine.core.pptx_text", fromlist=["x"]) \
                .make_text_frame(s, align="center", anchor="middle")
            gfit = fit_text(parse_rich(goal),
                            BBox(0, 0, inner.w - theme.spacing(0.6),
                                 goal_h - theme.spacing(0.4)),
                            ctx.font("body"), max_size=ctx.size("small"),
                            min_size=7.5, measurer=ctx.measurer)
            write_fit_result(tf, gfit, theme, family=ctx.font("body"),
                             align="center", default_color_role="ink")
            cursor += goal_h
            if i < len(spec.goals) - 1:
                aw = theme.spacing(1.6)
                add_shape(slide, BBox(inner.x + (inner.w - aw) // 2,
                                      cursor + theme.spacing(0.15), aw,
                                      arrow_h - theme.spacing(0.3)),
                          theme, shape="down_arrow", fill_role="accent")
                cursor += arrow_h

        if spec.cobenefits:
            cursor += theme.spacing(1.0)
            if spec.cobenefits_heading:
                hb = add_text_box(slide, BBox(inner.x, cursor, inner.w,
                                              inch(0.25)), align="center")
                write_spans_paragraph(hb.text_frame,
                                      [Span(spec.cobenefits_heading, bold=True)],
                                      ctx.size("micro"), theme,
                                      family=ctx.font("body"), align="center",
                                      default_color_role="inverse_ink")
                cursor += inch(0.28)
            for cb in spec.cobenefits:
                cbb = BBox(inner.x, cursor, inner.w, inch(0.46))
                s = add_shape(slide, cbb, theme, fill_role="bg")
                tf = make_text_frame(s, align="center", anchor="middle")
                cfit = fit_text(parse_rich(cb),
                                BBox(0, 0, inner.w - theme.spacing(0.6),
                                     cbb.h - theme.spacing(0.3)),
                                ctx.font("body"), max_size=ctx.size("micro"),
                                min_size=7.0, measurer=ctx.measurer)
                write_fit_result(tf, cfit, theme, family=ctx.font("body"),
                                 align="center", default_color_role="ink")
                cursor += inch(0.52)

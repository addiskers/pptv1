"""Assemblers for n_column_comparison, kpi_dashboard, data_deep_dive."""
from __future__ import annotations

from ..components.base import RenderContext
from ..layout.stacker import item, stack_into
from ..layout.stacker import plan as stacker_plan
from ..layout.stacker import render as stacker_render
from ..layout.zones import with_sidebar
from ..schema.components import (BulletListSpec, ComparisonColumnsSpec,
                                 SectionHeaderSpec, TextBlockSpec)
from ..schema.slide_types import (DataDeepDiveSpec, KpiDashboardSpec,
                                  NColumnComparisonSpec)
from .base import SlideAssembler, register_slide


@register_slide("n_column_comparison")
class NColumnComparison(SlideAssembler):
    def assemble(self, slide, spec: NColumnComparisonSpec,
                 ctx: RenderContext) -> None:
        z = self.zones(title_h=0.85 if not spec.subtitle else 1.1)
        stack_into(slide, z["title"], ctx, [
            item("section_header", SectionHeaderSpec(
                title=spec.title, subtitle=spec.subtitle, rule=False))])
        # summary band + footnote anchor to the BOTTOM of the body zone,
        # like the reference deck; the comparison grid gets the rest.
        bottom = []
        if spec.summary_band:
            bottom.append(item("callout_band", spec.summary_band))
        if spec.footnote:
            bottom.append(item("text_block", TextBlockSpec(
                text=spec.footnote, size_role="micro", color_role="ink_muted"),
                gap_before=0.5))
        comparison = [item("comparison_columns", ComparisonColumnsSpec(
            columns=spec.columns, row_labels=spec.row_labels), gap_before=0.8,
            flex=1.0)]
        if bottom:
            bplan = stacker_plan(bottom, z["body"], ctx, expand=False)
            band_bb, top_bb = z["body"].take_bottom(bplan.total)
            stack_into(slide, top_bb, ctx, comparison)
            stacker_render(slide, bplan, band_bb, ctx)
        else:
            stack_into(slide, z["body"], ctx, comparison)


@register_slide("kpi_dashboard")
class KpiDashboard(SlideAssembler):
    def assemble(self, slide, spec: KpiDashboardSpec, ctx: RenderContext) -> None:
        z = self.zones(title_h=0.85)
        stack_into(slide, z["title"], ctx, [
            item("section_header", SectionHeaderSpec(title=spec.title,
                                                     rule=False))])
        items = []
        for i, ist in enumerate(spec.icon_stats):
            items.append(item("icon_stat_row", ist,
                              gap_before=0.8 if i == 0 else 0.6))
        if spec.kpi_strip:
            items.append(item("kpi_card_strip", spec.kpi_strip, gap_before=1.2,
                              flex=1.0))
        if spec.highlight:
            items.append(item("highlight_box", spec.highlight, gap_before=1.2,
                              flex=0.6))
        if spec.footnote:
            items.append(item("text_block", TextBlockSpec(
                text=spec.footnote, size_role="micro", color_role="ink_muted"),
                gap_before=0.6))
        stack_into(slide, z["body"], ctx, items)


@register_slide("data_deep_dive")
class DataDeepDive(SlideAssembler):
    def assemble(self, slide, spec: DataDeepDiveSpec, ctx: RenderContext) -> None:
        z = self.zones(title_h=0.85 if not spec.subtitle else 1.1)
        stack_into(slide, z["title"], ctx, [
            item("section_header", SectionHeaderSpec(
                title=spec.title, subtitle=spec.subtitle, rule=False))])
        body = z["body"]
        if spec.insights:
            zones = with_sidebar(body, side_frac=0.26)
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
        main_items = []
        if spec.legend:
            main_items.append(item("legend_row", spec.legend, gap_before=0.6))
        main_items.append(item("data_table", spec.table, gap_before=0.8,
                               flex=1.0))
        if spec.footnote:
            main_items.append(item("text_block", TextBlockSpec(
                text=spec.footnote, size_role="micro", color_role="ink_muted"),
                gap_before=0.6))
        stack_into(slide, main, ctx, main_items)

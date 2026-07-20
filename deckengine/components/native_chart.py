"""native_chart — real editable PowerPoint charts that ARGUE.

Bar / stacked bar / line / donut via python-pptx's chart API (fully editable in
PowerPoint: right-click -> Edit Data). The spec forces rhetorical decisions:
sort order, one highlighted category (accent color), and an annotation callout.
Series colors cycle through theme roles; the highlight always wins.

Chart XML is the flakiest OOXML there is — style ONLY through the python-pptx
API here; any raw-XML fixup belongs in render/xml_utils.py.
"""
from __future__ import annotations

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.util import Emu, Pt

from ..core.bbox import BBox
from ..core.fit_text import Span
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, make_text_frame, write_spans_paragraph
from ..core.units import inch
from ..schema.components import NativeChartSpec
from .base import Component, RenderContext, register

_XL = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
       "stacked_bar": XL_CHART_TYPE.COLUMN_STACKED,
       "line": XL_CHART_TYPE.LINE,
       "donut": XL_CHART_TYPE.DOUGHNUT}
_SERIES_ROLES = ("primary", "accent", "positive", "primary_dark", "ink_muted",
                 "negative")
_ANNOT_H_MULT = 1.0  # annotation strip height in theme units (when present)


@register("native_chart")
class NativeChart(Component):
    spec_model = NativeChartSpec

    # -- data shaping (pure) ------------------------------------------------

    def _sorted(self, data: NativeChartSpec):
        cats = list(data.categories)
        series = [(s.name, list(s.values)) for s in data.series]
        n = min([len(cats)] + [len(v) for _, v in series])
        cats, series = cats[:n], [(nm, v[:n]) for nm, v in series]
        if data.sort in ("desc", "asc") and series:
            order = sorted(range(n), key=lambda i: series[0][1][i],
                           reverse=data.sort == "desc")
            cats = [cats[i] for i in order]
            series = [(nm, [v[i] for i in order]) for nm, v in series]
        return cats, series

    def _annot_h(self, data: NativeChartSpec, ctx: RenderContext) -> int:
        return ctx.theme.spacing(2.4) if data.annotation else 0

    def measure(self, data: NativeChartSpec, width: int,
                ctx: RenderContext) -> int:
        natural = min(max(round(width * 0.48), inch(2.2)), inch(3.4))
        return natural + self._annot_h(data, ctx)

    # -- render --------------------------------------------------------------

    def render(self, slide, data: NativeChartSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        annot_h = self._annot_h(data, ctx)
        total = self.measure(data, bbox.w, ctx)
        if ctx.fill_hint and bbox.h > total:
            total = bbox.h  # charts fill their zone gracefully
        chart_h = max(inch(1.6), total - annot_h)

        cats, series = self._sorted(data)
        cd = CategoryChartData()
        cd.categories = cats
        for name, values in series:
            cd.add_series(name, values)

        frame = slide.shapes.add_chart(
            _XL[data.chart_type], Emu(bbox.x), Emu(bbox.y),
            Emu(bbox.w), Emu(chart_h), cd)
        chart = frame.chart
        self._style(chart, data, cats, series, ctx)

        if data.annotation:
            strip = BBox(bbox.x, bbox.y + chart_h + theme.spacing(0.4),
                         bbox.w, annot_h - theme.spacing(0.4))
            bar, text = strip.take_left(theme.spacing(0.35))
            add_shape(slide, bar, theme, fill_role="accent")
            box = add_text_box(slide, text.inset(left=theme.spacing(0.4)),
                               anchor="middle")
            write_spans_paragraph(box.text_frame,
                                  [Span(data.annotation, bold=True)],
                                  ctx.size("small"), theme,
                                  family=ctx.font("body"),
                                  default_color_role="ink")
        return total

    def _style(self, chart, data: NativeChartSpec, cats, series,
               ctx: RenderContext) -> None:
        theme = ctx.theme
        chart.has_title = False
        chart.font.size = Pt(theme.size_micro)
        chart.font.name = ctx.font("body")
        chart.font.color.rgb = RGBColor.from_string(theme.color("ink"))

        multi = len(series) > 1
        chart.has_legend = multi
        if multi:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
            chart.legend.font.size = Pt(theme.size_micro)

        for si, plot_series in enumerate(chart.series):
            role = _SERIES_ROLES[si % len(_SERIES_ROLES)]
            if data.chart_type == "line":
                plot_series.format.line.color.rgb = RGBColor.from_string(
                    theme.color(role))
                plot_series.format.line.width = Pt(2.25)
                plot_series.smooth = False
            else:
                plot_series.format.fill.solid()
                plot_series.format.fill.fore_color.rgb = RGBColor.from_string(
                    theme.color(role))

        # highlight one category in accent (single-series bar/donut only —
        # that's where per-point emphasis reads correctly)
        if (data.highlight and data.highlight in cats and not multi
                and data.chart_type in ("bar", "donut")):
            idx = cats.index(data.highlight)
            point = chart.series[0].points[idx]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = RGBColor.from_string(
                theme.color("accent"))

        # donut: colored slices per category when single-series
        if data.chart_type == "donut" and not multi:
            for pi, point in enumerate(chart.series[0].points):
                if data.highlight and pi == (cats.index(data.highlight)
                                             if data.highlight in cats else -1):
                    continue
                role = _SERIES_ROLES[pi % len(_SERIES_ROLES)]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = RGBColor.from_string(
                    theme.color(role))

        # value axis: light gridlines, micro labels (bar/line only)
        if data.chart_type in ("bar", "stacked_bar", "line"):
            va = chart.value_axis
            va.has_major_gridlines = True
            va.major_gridlines.format.line.color.rgb = RGBColor.from_string(
                theme.color("grid"))
            va.major_gridlines.format.line.width = Pt(0.5)
            va.format.line.fill.background()
            va.tick_labels.font.size = Pt(theme.size_micro)
            ca = chart.category_axis
            ca.format.line.color.rgb = RGBColor.from_string(theme.color("grid"))
            ca.tick_labels.font.size = Pt(theme.size_micro)
            # single-series bar: value labels on bars, no y-axis clutter
            if data.chart_type == "bar" and not multi:
                plot = chart.plots[0]
                plot.has_data_labels = True
                dl = plot.data_labels
                dl.font.size = Pt(theme.size_micro)
                dl.font.bold = True
                dl.font.color.rgb = RGBColor.from_string(theme.color("ink"))
                dl.number_format = f'0"{data.value_suffix}"'
                dl.number_format_is_linked = False

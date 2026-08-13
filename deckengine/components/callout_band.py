"""callout_band — the reference bottom TOTAL band.

Full-width surface panel with a thin grid outline; an optional rounded label
tab straddling the top edge (vertical center on the band top); an optional
icon circle at left; and 1-5 equal-width text segments separated by thin
vertical rules.

The icon circle diameter tracks the band height, and the band height depends
on how the segments wrap in the remaining width — a fixed point resolved by a
short deterministic loop of pure math shared by measure() and render().
Consumed height = tab overhang (spacing(0.6), if labelled) + band height; the
tab is drawn ABOVE the band top but inside the given bbox.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_shape, add_vline
from ..core.pptx_text import add_text_box, make_text_frame, write_fit_result, \
    write_spans_paragraph
from ..core.units import inch, pt
from ..schema.components import CalloutBandSpec
from ..schema.rich import parse_rich, plain
from .base import Component, RenderContext, register

_MIN_BAND_H = inch(0.9)
_PROBE_H = inch(11)        # generous probe: fit decides its own natural height
_MIN_SEG_PT = 7.5


@dataclass(frozen=True)
class _BandLayout:
    band_h: int
    pad: int         # inner padding from the band edges
    inset: int       # horizontal text inset inside each segment cell
    dia: int         # icon circle diameter (0 when no icon)
    seg_x0: int      # segment area offset from the band's left edge
    seg_w: int       # total segment area width
    fits: list[FitResult]


@register("callout_band")
class CalloutBand(Component):
    spec_model = CalloutBandSpec

    # -- pure layout math (no side effects) -------------------------------

    def _fit_at(self, seg_spans: list[list[Span]], data: CalloutBandSpec,
                width: int, band_h: int, ctx: RenderContext) -> _BandLayout:
        sp = ctx.theme.spacing
        pad = sp(0.6)
        inset = sp(0.4)
        dia = max(0, band_h - sp(1.0)) if data.icon else 0
        seg_x0 = pad + (dia + pad if data.icon else 0)
        seg_w = max(0, width - seg_x0 - pad)
        cols = BBox(0, 0, seg_w, _PROBE_H).cols(len(seg_spans))
        fits = [
            fit_text(spans, BBox(0, 0, max(0, col.w - 2 * inset), _PROBE_H),
                     ctx.font("body"), max_size=ctx.size("small"),
                     min_size=_MIN_SEG_PT, measurer=ctx.measurer)
            for spans, col in zip(seg_spans, cols)
        ]
        return _BandLayout(band_h, pad, inset, dia, seg_x0, seg_w, fits)

    def _layout(self, data: CalloutBandSpec, width: int,
                ctx: RenderContext) -> _BandLayout:
        seg_spans = [parse_rich(s, base_color_role="ink")
                     for s in data.segments]
        band_h = _MIN_BAND_H
        for _ in range(3):
            lay = self._fit_at(seg_spans, data, width, band_h, ctx)
            need = max(max(f.height_emu for f in lay.fits)
                       + ctx.theme.spacing(1.6), _MIN_BAND_H)
            if need <= band_h:
                return lay
            band_h = need
        # rare non-convergence: settle at the last height, refit consistently
        return self._fit_at(seg_spans, data, width, band_h, ctx)

    def _overhang(self, data: CalloutBandSpec, ctx: RenderContext) -> int:
        return ctx.theme.spacing(0.6) if data.label else 0

    @staticmethod
    def _blank(data: CalloutBandSpec) -> bool:
        """All-blank payload: an empty surface band is a layout bug, not
        content — measure 0 so the stacker drops it entirely."""
        return (not (data.label or "").strip() and not (data.icon or "").strip()
                and not any(plain(s).strip() for s in data.segments))

    # -- contract ----------------------------------------------------------

    def measure(self, data: CalloutBandSpec, width: int,
                ctx: RenderContext) -> int:
        if self._blank(data):
            return 0
        return self._layout(data, width, ctx).band_h + self._overhang(data, ctx)

    def render(self, slide, data: CalloutBandSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        if self._blank(data):
            ctx.report.warn("callout_band: all-blank payload; skipped")
            return 0
        theme = ctx.theme
        lay = self._layout(data, bbox.w, ctx)
        overhang = self._overhang(data, ctx)
        band = BBox(bbox.x, bbox.y + overhang, bbox.w, lay.band_h)

        # panel
        add_shape(slide, band, theme, shape="rect", fill_role="surface",
                  line_role="grid", line_w_pt=0.75)

        # segments: equal columns, centered text, vertically middle-anchored
        seg_area = BBox(band.x + lay.seg_x0, band.y, lay.seg_w, band.h)
        cols = seg_area.cols(len(data.segments))
        for col, fit, src in zip(cols, lay.fits, data.segments):
            if fit.truncated:
                ctx.report.truncated(f"callout_band segment: {src[:40]!r}")
            cell = col.inset(left=lay.inset, right=lay.inset)
            box = add_text_box(slide, cell, align="center", anchor="middle")
            write_fit_result(box.text_frame, fit, theme,
                             family=ctx.font("body"), align="center",
                             default_color_role="ink")

        # thin separators between segments, inset from the band edges
        v_inset = theme.spacing(0.5)
        for col in cols[1:]:
            add_vline(slide, col.x, band.y + v_inset,
                      max(0, band.h - 2 * v_inset), theme, role="grid",
                      weight_pt=0.5)

        # icon circle at left inside the padding
        if data.icon:
            circle = BBox(band.x + lay.pad, band.y + (band.h - lay.dia) // 2,
                          lay.dia, lay.dia)
            s = add_shape(slide, circle, theme, shape="oval",
                          fill_role="positive")
            tf = make_text_frame(s, align="center", anchor="middle")
            write_spans_paragraph(
                tf, [Span(data.icon, color_role="inverse_ink")],
                ctx.size("h2"), theme, family=ctx.font("body"), align="center")

        # rounded label tab, vertical center on the band's top edge
        if data.label:
            tab_h = overhang * 2
            label_w = pt(ctx.measurer.width_pt(data.label, ctx.font("body"),
                                               ctx.size("micro"), bold=True))
            tab_w = min(band.w, label_w + theme.spacing(1.0))
            tab = BBox(band.x + (band.w - tab_w) // 2, band.y - overhang,
                       tab_w, tab_h)
            s = add_shape(slide, tab, theme, shape="rounded",
                          fill_role="positive", corner_radius=0.5)
            tf = make_text_frame(s, align="center", anchor="middle")
            write_spans_paragraph(
                tf, [Span(data.label, bold=True, color_role="inverse_ink")],
                ctx.size("micro"), theme, family=ctx.font("body"),
                align="center")

        total = overhang + lay.band_h
        if total > bbox.h:
            ctx.report.warn("callout_band: taller than provided bbox")
        return total

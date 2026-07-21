"""progress_pill — labeled progress bar (FMD-vaccination-bar style).

A rich label line on top; below it, a full-width rounded track filled
'surface_alt' (height = one 'micro' line + spacing(0.3)) with a rounded
'primary' segment sized to value_pct (min width = its own height so the pill
never degenerates). data.display rides centered INSIDE the segment in bold
inverse micro text when it fits, else just right of the segment in 'ink'.
An optional target_display sits right-aligned at the track end in 'ink_muted'.

Height = label fit + spacing(0.25) + track height.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, write_spans_paragraph, \
    write_fit_result
from ..core.units import inch, to_pt
from ..schema.components import ProgressPillSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_CORNER_RADIUS = 0.5      # full pill on track and segment
_TRACK_PAD_MULT = 0.3     # spacing multiple added to one micro line
_GAP_MULT = 0.25          # spacing multiple between label and track
_INSIDE_PAD_MULT = 0.5    # display fits inside if narrower by this padding
_OUT_GAP_MULT = 0.2       # gap between segment and an outside display
_MIN_LABEL_PT = 7.5
_PROBE_H = inch(11)       # generous probe: fit decides its own natural height


@register("progress_pill")
class ProgressPill(Component):
    spec_model = ProgressPillSpec

    # -- pure layout math (no side effects) --------------------------------

    def _track_h(self, ctx: RenderContext) -> int:
        line_h = ctx.measurer.line_height_emu(
            [Span("Ag", bold=True)], ctx.font("body"), ctx.size("micro"))
        return line_h + ctx.theme.spacing(_TRACK_PAD_MULT)

    def _label_fit(self, data: ProgressPillSpec, width: int,
                   ctx: RenderContext) -> FitResult:
        ink = "inverse_ink" if data.inverse else "ink"
        return fit_text(parse_rich(data.label, base_color_role=ink),
                        BBox(0, 0, max(1, width), _PROBE_H), ctx.font("body"),
                        max_size=ctx.size("small"), min_size=_MIN_LABEL_PT,
                        measurer=ctx.measurer)

    # -- contract -----------------------------------------------------------

    def measure(self, data: ProgressPillSpec, width: int,
                ctx: RenderContext) -> int:
        return (self._label_fit(data, width, ctx).height_emu
                + ctx.theme.spacing(_GAP_MULT) + self._track_h(ctx))

    def render(self, slide, data: ProgressPillSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        family = ctx.font("body")
        size_micro = ctx.size("micro")
        ink = "inverse_ink" if data.inverse else "ink"
        label_fit = self._label_fit(data, bbox.w, ctx)
        gap = theme.spacing(_GAP_MULT)
        track_h = self._track_h(ctx)

        # label line on top
        if label_fit.truncated:
            ctx.report.truncated(f"progress_pill label: {data.label[:40]!r}")
        lbox = add_text_box(slide, BBox(bbox.x, bbox.y, bbox.w,
                                        label_fit.height_emu))
        write_fit_result(lbox.text_frame, label_fit, theme, family=family,
                         default_color_role=ink)

        # track + fill segment
        track_y = bbox.y + label_fit.height_emu + gap
        track = BBox(bbox.x, track_y, bbox.w, track_h)
        add_shape(slide, track, theme, shape="rounded",
                  fill_role="surface_alt", corner_radius=_CORNER_RADIUS)
        seg_w = min(track.w,
                    max(round(track.w * data.value_pct / 100.0), track_h))
        seg = BBox(track.x, track_y, seg_w, track_h)
        add_shape(slide, seg, theme, shape="rounded", fill_role="primary",
                  corner_radius=_CORNER_RADIUS)

        # display: inside the segment when it fits, else just right of it
        line_pt = to_pt(ctx.measurer.line_height_emu(
            [Span("Ag", bold=True)], family, size_micro))
        disp_w = ctx.measurer.span_width_emu(
            Span(data.display, bold=True), family, size_micro)
        out_x = seg.right + theme.spacing(_OUT_GAP_MULT)
        out_w = track.right - out_x
        if disp_w + theme.spacing(_INSIDE_PAD_MULT) <= seg.w:
            dbox = add_text_box(slide, seg, align="center", anchor="middle")
            write_spans_paragraph(
                dbox.text_frame,
                [Span(data.display, bold=True, color_role="inverse_ink")],
                size_micro, theme, family=family, align="center",
                line_spacing_pt=line_pt, default_color_role="inverse_ink")
        elif disp_w <= out_w:
            # rides ON the light track — dark ink regardless of data.inverse
            dbox = add_text_box(slide, BBox(out_x, track_y, out_w, track_h),
                                anchor="middle")
            write_spans_paragraph(
                dbox.text_frame,
                [Span(data.display, bold=True, color_role="ink")],
                size_micro, theme, family=family,
                line_spacing_pt=line_pt, default_color_role="ink")
        else:
            ctx.report.warn(
                f"progress_pill: display {data.display!r} fits neither inside "
                "nor beside the fill segment; placed inside")
            dbox = add_text_box(slide, seg, align="center", anchor="middle")
            write_spans_paragraph(
                dbox.text_frame,
                [Span(data.display, bold=True, color_role="inverse_ink")],
                size_micro, theme, family=family, align="center",
                line_spacing_pt=line_pt, default_color_role="inverse_ink")

        # optional target, right-aligned at the track end
        if data.target_display is not None:
            tgt_w = ctx.measurer.span_width_emu(
                Span(data.target_display), family, size_micro)
            if (disp_w + theme.spacing(_INSIDE_PAD_MULT) > seg.w
                    and disp_w <= out_w
                    and out_x + disp_w + theme.spacing(_OUT_GAP_MULT)
                    > track.right - tgt_w):
                ctx.report.warn(
                    "progress_pill: target_display overlaps the display text")
            # also ON the track — keep muted dark ink even on inverse cards
            tbox = add_text_box(slide, track, align="right", anchor="middle")
            write_spans_paragraph(
                tbox.text_frame,
                [Span(data.target_display, color_role="ink_muted")],
                size_micro, theme, family=family, align="right",
                line_spacing_pt=line_pt, default_color_role="ink_muted")

        return label_fit.height_emu + gap + track_h

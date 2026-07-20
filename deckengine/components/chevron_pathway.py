"""chevron_pathway — row of N chevron process steps spanning the width.

Each step is a 'chevron' shape filled 'primary_dark'; the step at
highlight_index (if any) fills 'accent' instead. Step text is bold 'small'
'inverse_ink', centered and middle-anchored, fit to at most two lines within
the chevron width minus spacing(0.8) insets each side (the arrow points eat
into the writable area).

Height is fixed: two 'small' lines + spacing(0.6). measure() returns exactly
that; render() consumes exactly that.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import make_text_frame, write_spans_paragraph
from ..core.units import to_inch
from ..schema.components import ChevronPathwaySpec
from .base import Component, RenderContext, register

_GAP_MULT = 0.15      # overlap-gap between adjacent chevrons
_INSET_MULT = 0.8     # horizontal text inset, each side
_PAD_MULT = 0.6       # vertical padding added to the two reserved lines
_MIN_SMALL = 7.5      # shrink floor for step text
_MAX_LINES = 2
_PROBE_H = 10_000_000  # fit decides real height; probe never truncates
_TEXT_ROLE = "inverse_ink"
_FILL_ROLE = "primary_dark"
_HIGHLIGHT_ROLE = "accent"


@register("chevron_pathway")
class ChevronPathway(Component):
    spec_model = ChevronPathwaySpec

    # -- shared math (side-effect free) ------------------------------------

    def _height(self, ctx: RenderContext) -> int:
        line_h = ctx.measurer.line_height_emu(
            [Span("Ag", bold=True)], ctx.font("body"), ctx.size("small"))
        return _MAX_LINES * line_h + ctx.theme.spacing(_PAD_MULT)

    # -- contract ------------------------------------------------------------

    def measure(self, data: ChevronPathwaySpec, width: int,
                ctx: RenderContext) -> int:
        return self._height(ctx)

    def render(self, slide, data: ChevronPathwaySpec, bbox: BBox,
               ctx: RenderContext) -> int:
        height = self._height(ctx)
        if height > bbox.h:
            ctx.report.warn(
                f"chevron_pathway: needs {to_inch(height):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")

        n = len(data.steps)
        highlight = data.highlight_index
        if highlight is not None and not 0 <= highlight < n:
            ctx.report.warn(
                f"chevron_pathway: highlight_index {highlight} out of range "
                f"for {n} steps; ignoring")
            highlight = None

        family = ctx.font("body")
        inset = ctx.theme.spacing(_INSET_MULT)
        cols = BBox(bbox.x, bbox.y, bbox.w, height).cols(
            n, gap=ctx.theme.spacing(_GAP_MULT))

        for i, (step, col) in enumerate(zip(data.steps, cols)):
            fill = _HIGHLIGHT_ROLE if i == highlight else _FILL_ROLE
            chev = add_shape(slide, col, ctx.theme, shape="chevron",
                             fill_role=fill)
            fit = fit_text([Span(step, bold=True, color_role=_TEXT_ROLE)],
                           BBox(0, 0, max(0, col.w - 2 * inset), _PROBE_H),
                           family, max_size=ctx.size("small"),
                           min_size=_MIN_SMALL, max_lines=_MAX_LINES,
                           measurer=ctx.measurer)
            if fit.truncated:
                ctx.report.truncated(f"chevron_pathway: {step[:40]!r}")
            tf = make_text_frame(chev, align="center", anchor="middle")
            for j, line in enumerate(fit.lines):
                write_spans_paragraph(
                    tf, line.spans, fit.size_pt, ctx.theme, family=family,
                    align="center", line_spacing_pt=fit.line_spacing_pt,
                    default_color_role=_TEXT_ROLE,
                    paragraph=tf.paragraphs[0] if j == 0
                    else tf.add_paragraph())
        return height

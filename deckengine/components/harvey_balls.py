"""harvey_balls — one row of quarter-filled rating balls with labels.

Reference look: the classic consulting option-scoring vocabulary — up to
six criteria side by side, each a small ink-rimmed ball whose 'primary'
fill shows a 0-4 score in quarter steps, label sitting right of its ball.

Ball anatomy by score: 0 draws nothing under the rim; 4 draws a full
'primary' oval; 1-3 reuse donut_stat._add_pie (12 o'clock start, one
quarter-turn clockwise per point — see its adjustment-unit docstring).
The fill goes down first and the unfilled outline oval last so the rim
stays crisp over the wedge edge.

measure(): pure fit_text math on per-cell label widths; row height is
max(ball diameter, tallest label) plus trailing spacing. render(): same
_plan, then per cell wedge/fill, rim, and a middle-anchored label box.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.fit_text import FitResult, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, write_fit_result
from ..core.units import inch
from ..schema.components import HarveyBallsSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register
from .donut_stat import _add_pie

_BALL_D = inch(0.32)
_RIM_W_PT = 1.25
_CELL_GAP_MULT = 0.5   # between cells
_BALL_GAP_MULT = 0.8   # between ball and label (labels must not kiss the rim)
_PAD_MULT = 0.3        # trailing spacing (see height contract)
_MIN_LABEL_PT = 7.5
_MAX_LABEL_LINES = 2
_START_DEG = -90.0     # 12 o'clock; the wedge sweeps clockwise
_DEG_PER_SCORE = 90.0  # one quarter turn per score point
_PROBE_H = inch(11)    # generous probe: fit decides its own natural height


@register("harvey_balls")
class HarveyBalls(Component):
    spec_model = HarveyBallsSpec

    # -- pure layout math (no side effects) --------------------------------

    def _plan(self, data: HarveyBallsSpec, width: int,
              ctx: RenderContext) -> tuple[list[FitResult], int, int]:
        gap = ctx.theme.spacing(_BALL_GAP_MULT)
        cols = BBox(0, 0, width, _PROBE_H).cols(
            len(data.items), gap=ctx.theme.spacing(_CELL_GAP_MULT))
        fits: list[FitResult] = []
        label_h = 0
        for item, col in zip(data.items, cols):
            fit = fit_text(parse_rich(item.label, base_color_role="ink"),
                           BBox(0, 0, max(1, col.w - _BALL_D - gap),
                                _PROBE_H),
                           ctx.font("body"), max_size=ctx.size("small"),
                           min_size=_MIN_LABEL_PT,
                           max_lines=_MAX_LABEL_LINES,
                           measurer=ctx.measurer)
            fits.append(fit)
            label_h = max(label_h, fit.height_emu)
        content_h = max(_BALL_D, label_h)
        return fits, content_h, content_h + ctx.theme.spacing(_PAD_MULT)

    # -- contract -----------------------------------------------------------

    def measure(self, data: HarveyBallsSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx)[2]

    def render(self, slide, data: HarveyBallsSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        fits, content_h, height = self._plan(data, bbox.w, ctx)
        gap = theme.spacing(_BALL_GAP_MULT)
        cols = bbox.cols(len(data.items), gap=theme.spacing(_CELL_GAP_MULT))
        for item, fit, col in zip(data.items, fits, cols):
            ball = BBox(col.x, col.y + (content_h - _BALL_D) // 2,
                        _BALL_D, _BALL_D)
            # fill under the rim: full oval at 4, wedge at 1-3, none at 0
            if item.score >= 4:
                add_shape(slide, ball, theme, shape="oval",
                          fill_role="primary")
            elif item.score > 0:
                _add_pie(slide, ball, theme, fill_role="primary",
                         start_deg=_START_DEG,
                         end_deg=_START_DEG + item.score * _DEG_PER_SCORE)
            add_shape(slide, ball, theme, shape="oval",
                      line_role="ink", line_w_pt=_RIM_W_PT)
            if fit.truncated:
                ctx.report.truncated(
                    f"harvey_balls label: {item.label[:40]!r}")
            lbox = add_text_box(
                slide, BBox(col.x + _BALL_D + gap, col.y,
                            max(1, col.w - _BALL_D - gap), content_h),
                align="left", anchor="middle")
            write_fit_result(lbox.text_frame, fit, theme,
                             family=ctx.font("body"), align="left")
        if height > bbox.h:
            ctx.report.warn("harvey_balls: content taller than provided bbox")
        return height

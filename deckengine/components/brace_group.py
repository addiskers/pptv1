"""brace_group — stacked content } takeaway.

Reference look: the Gates impact slide's bracket grouping the state table to
the conclusion beside it. Children stack on the left, a line-only RIGHT_BRACE
spans their height, and the takeaway sits middle-anchored to the right.

Children resolve through the component registry (same pattern as
comparison_columns) so this module never imports sibling components.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, fit_text
from ..core.pptx_shapes import add_shape
from ..core.pptx_text import add_text_box, write_fit_result
from ..core.units import inch
from ..schema.components import BraceGroupSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, get_component, register

_BRACE_W = inch(0.22)
_MIN_TAKEAWAY_PT = 9.0
_PROBE_H = inch(11)


@dataclass(frozen=True)
class _Plan:
    content_w: int
    takeaway_w: int
    gap: int              # gutter either side of the brace
    child_gap: int        # vertical gap between stacked children
    child_hs: tuple[int, ...]
    content_h: int
    takeaway_fit: FitResult
    total: int


@register("brace_group")
class BraceGroup(Component):
    spec_model = BraceGroupSpec

    # -- shared planning (side-effect free) --------------------------------

    def _plan(self, data: BraceGroupSpec, width: int,
              ctx: RenderContext) -> _Plan:
        theme = ctx.theme
        gap = theme.spacing(0.4)
        child_gap = theme.spacing(0.5)
        takeaway_w = round(width * data.takeaway_frac)
        content_w = max(1, width - takeaway_w - _BRACE_W - 2 * gap)
        child_hs = tuple(
            get_component(c.kind).measure(c, content_w, ctx)
            for c in data.content)
        content_h = sum(child_hs) + child_gap * (len(child_hs) - 1)
        takeaway_fit = fit_text(
            parse_rich(data.takeaway, base_color_role="ink"),
            BBox(0, 0, takeaway_w, _PROBE_H), ctx.font("body"),
            max_size=ctx.size("h2"), min_size=_MIN_TAKEAWAY_PT,
            measurer=ctx.measurer)
        total = max(content_h, takeaway_fit.height_emu)
        return _Plan(content_w=content_w, takeaway_w=takeaway_w, gap=gap,
                     child_gap=child_gap, child_hs=child_hs,
                     content_h=content_h, takeaway_fit=takeaway_fit,
                     total=total)

    # -- contract -----------------------------------------------------------

    def measure(self, data: BraceGroupSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: BraceGroupSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w, ctx)
        kept = list(data.content)
        if plan.total > bbox.h:
            # a canvas cell can be shorter than the natural stack: keep the
            # leading children that FIT, drop the rest (reported), refit the
            # takeaway into the cell — the group never paints past its box
            hs = list(plan.child_hs)
            acc, n_fit = 0, 0
            for i, h in enumerate(hs):
                nxt = acc + h + (plan.child_gap if i else 0)
                if nxt > bbox.h and n_fit >= 1:
                    break
                acc, n_fit = nxt, i + 1
            if n_fit < len(kept):
                ctx.report.truncated(
                    f"brace_group: {len(kept) - n_fit} child(ren) dropped")
                kept = kept[:n_fit]
                hs = hs[:n_fit]
            content_h = sum(hs) + plan.child_gap * (len(hs) - 1)
            takeaway_fit = fit_text(
                parse_rich(data.takeaway, base_color_role="ink"),
                BBox(0, 0, plan.takeaway_w, bbox.h), ctx.font("body"),
                max_size=ctx.size("h2"), min_size=_MIN_TAKEAWAY_PT,
                measurer=ctx.measurer)
            total = max(content_h, min(takeaway_fit.height_emu, bbox.h))
            plan = _Plan(content_w=plan.content_w,
                         takeaway_w=plan.takeaway_w, gap=plan.gap,
                         child_gap=plan.child_gap, child_hs=tuple(hs),
                         content_h=content_h, takeaway_fit=takeaway_fit,
                         total=total)
            if total > bbox.h:
                ctx.report.warn(
                    f"brace_group: content height {total} exceeds bbox "
                    f"height {bbox.h}")

        # children, top-aligned within the group's own height
        y = bbox.y + (plan.total - plan.content_h) // 2
        for child, h in zip(kept, plan.child_hs):
            get_component(child.kind).render(
                slide, child, BBox(bbox.x, y, plan.content_w, h), ctx)
            y += h + plan.child_gap

        # line-only brace spanning the content height
        brace = BBox(bbox.x + plan.content_w + plan.gap,
                     bbox.y + (plan.total - plan.content_h) // 2,
                     _BRACE_W, plan.content_h)
        add_shape(slide, brace, theme, shape="right_brace",
                  line_role="ink", line_w_pt=1.25)

        # takeaway, middle-anchored against the group
        if plan.takeaway_fit.truncated:
            ctx.report.truncated(f"brace_group takeaway: {data.takeaway[:40]!r}")
        tbox = add_text_box(
            slide, BBox(brace.right + plan.gap, bbox.y, plan.takeaway_w,
                        plan.total), anchor="middle")
        write_fit_result(tbox.text_frame, plan.takeaway_fit, theme,
                         family=ctx.font("body"), default_color_role="ink")
        return plan.total

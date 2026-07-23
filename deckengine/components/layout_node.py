"""rows / cols / panel — layout nodes ARE components (Q2).

Not a new engine: `rows` reuses the vertical stacking arithmetic, `cols`
copies comparison_columns' shared-plan equal-height pattern, `panel`
decorates then delegates. Because nodes are registered components,
get_component resolves them anywhere a leaf can appear — trees nest freely
and keep measure/render parity.

Fill contract: with ctx.fill_hint set (custom_layout sets it on the root),
`rows` with fracs allocates the WHOLE assigned height by share and passes
fill_hint down into each cell; `cols` stretches its shared track to the cell;
`panel` grows to the cell and offers the surplus to its child. Without
fill_hint every node renders at natural height — parity with measure().
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.pptx_shapes import add_shape
from ..schema.layout_tree import ColsNode, PanelNode, RowsNode
from .base import Component, RenderContext, get_component, register


def _child_fill(ctx: RenderContext, on: bool):
    """Temporarily set ctx.fill_hint around a child render."""
    class _Guard:
        def __enter__(self):
            self.prev = ctx.fill_hint
            ctx.fill_hint = on

        def __exit__(self, *exc):
            ctx.fill_hint = self.prev
    return _Guard()


@register("rows")
class Rows(Component):
    spec_model = RowsNode

    def measure(self, data: RowsNode, width: int, ctx: RenderContext) -> int:
        g = ctx.theme.spacing(data.gap)
        return (sum(get_component(c.kind).measure(c, width, ctx)
                    for c in data.children) + g * (len(data.children) - 1))

    def render(self, slide, data: RowsNode, bbox: BBox,
               ctx: RenderContext) -> int:
        g = ctx.theme.spacing(data.gap)
        natural = [get_component(c.kind).measure(c, bbox.w, ctx)
                   for c in data.children]
        total_nat = sum(natural) + g * (len(natural) - 1)
        surplus = bbox.h - total_nat
        fill = ctx.fill_hint and data.fracs is not None and surplus > 0
        pin = (ctx.fill_hint and not fill and data.pin_last
               and surplus > 0 and len(natural) > 1)
        if fill:
            avail = bbox.h - g * (len(natural) - 1)
            heights = [round(avail * f) for f in data.fracs]
        else:
            heights = natural
            if ctx.fill_hint and surplus > 0 and len(natural) > 1:
                # no fracs: breathe like the stacker — gaps may double
                # (when pinning, keep one base gap clear of the pinned child)
                lead = max(0, surplus - g) if pin else surplus
                g += min(lead // (len(natural) - 1), g)
        y = bbox.y
        last = len(data.children) - 1
        for i, (child, h, nat) in enumerate(zip(data.children, heights,
                                                natural)):
            if h < nat:
                ctx.report.warn(
                    f"rows: child '{child.kind}' natural {nat} exceeds its "
                    f"frac cell {h}; content may overflow")
            if pin and i == last:
                y = bbox.bottom - nat  # anchored to the zone bottom
            cell = BBox(bbox.x, y, bbox.w, h)
            with _child_fill(ctx, fill and h > nat):
                consumed = get_component(child.kind).render(slide, child,
                                                            cell, ctx)
            y += (h if fill else consumed) + g
        return bbox.h if (fill or pin) else y - g - bbox.y


@register("cols")
class Cols(Component):
    spec_model = ColsNode

    # -- shared plan (side-effect free) -------------------------------------

    def _boxes(self, data: ColsNode, region: BBox,
               ctx: RenderContext) -> list[BBox]:
        gap = ctx.theme.spacing(data.gap)
        if data.fracs is None:
            return region.cols(len(data.children), gap=gap)
        total = sum(data.fracs)
        avail = region.w - gap * (len(data.children) - 1)
        boxes, x = [], region.x
        for f in data.fracs:
            w = round(avail * f / total)
            boxes.append(BBox(x, region.y, w, region.h))
            x += w + gap
        return boxes

    def _plan(self, data: ColsNode, width: int,
              ctx: RenderContext) -> tuple[list[BBox], list[int], int]:
        boxes = self._boxes(data, BBox(0, 0, width, 1), ctx)
        heights = [get_component(c.kind).measure(c, b.w, ctx)
                   for c, b in zip(data.children, boxes)]
        return boxes, heights, max(heights)

    # -- contract -----------------------------------------------------------

    def measure(self, data: ColsNode, width: int, ctx: RenderContext) -> int:
        return self._plan(data, width, ctx)[2]

    def render(self, slide, data: ColsNode, bbox: BBox,
               ctx: RenderContext) -> int:
        _, heights, track_h = self._plan(data, bbox.w, ctx)
        cell_h = bbox.h if (ctx.fill_hint and bbox.h > track_h) else track_h
        boxes = self._boxes(data, bbox.with_height(cell_h), ctx)
        for child, b, nat in zip(data.children, boxes, heights):
            if data.align == "middle" and b.h > nat:
                # exactly the natural box, vertically centered — no stretch
                cell = BBox(b.x, b.y + (b.h - nat) // 2, b.w, nat)
                fill_child = False
            else:
                cell = b
                fill_child = cell.h > nat
            with _child_fill(ctx, fill_child):
                get_component(child.kind).render(slide, child, cell, ctx)
        return cell_h


@register("panel")
class Panel(Component):
    spec_model = PanelNode

    def _pad(self, data: PanelNode, ctx: RenderContext) -> int:
        return ctx.theme.spacing(data.inset)

    def measure(self, data: PanelNode, width: int, ctx: RenderContext) -> int:
        pad = self._pad(data, ctx)
        inner_w = max(1, width - 2 * pad)
        return (get_component(data.child.kind).measure(data.child, inner_w, ctx)
                + 2 * pad)

    def render(self, slide, data: PanelNode, bbox: BBox,
               ctx: RenderContext) -> int:
        pad = self._pad(data, ctx)
        natural = self.measure(data, bbox.w, ctx)
        h = bbox.h if (ctx.fill_hint and bbox.h > natural) else natural
        if data.fill_role or data.border_role:
            add_shape(slide, bbox.with_height(h), ctx.theme,
                      shape="rounded" if data.rounded else "rect",
                      fill_role=data.fill_role, line_role=data.border_role,
                      line_w_pt=1.25, corner_radius=0.08,
                      shadow=data.shadow)
        inner = BBox(bbox.x + pad, bbox.y + pad,
                     max(1, bbox.w - 2 * pad), h - 2 * pad)
        with _child_fill(ctx, h > natural):
            get_component(data.child.kind).render(slide, data.child, inner, ctx)
        return h

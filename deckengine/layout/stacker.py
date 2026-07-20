"""Two-phase vertical stacker with a symmetric fit cascade.

Layout is a pure function of (items, bbox, cascade level): plan() measures
everything and picks the level as DATA; render() then draws exactly once.

The cascade runs BOTH directions:
- overflow  -> compress gaps (1.0 -> 0.75 -> 0.5), then accept + warn
- underflow -> expand gaps (up to 1.5x), then distribute surplus to
  flex-capable items (StackItem.flex weights), then cap-center the block.

Dead space at the bottom of a slide is the #1 machine-made-deck tell; the
expansion path is what makes generated decks fill the page like the
hand-built references.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from ..components.base import Component, RenderContext, get_component
from ..core.bbox import BBox
from ..core.units import inch

GAP_LEVELS = (1.0, 0.75, 0.5)      # compression steps
GAP_EXPAND_MAX = 2.0               # gaps may grow to 1.5x when underfull
FILL_TARGET = 0.85                 # expand when content < 85% of the zone
CENTER_CAP = inch(0.45)            # max vertical-centering offset
FLEX_GROWTH_CAP = 0.6              # a flex item may grow at most 60% over natural


@dataclass
class StackItem:
    component: Component
    data: BaseModel
    gap_before: float = 1.0   # multiples of theme.unit, scaled by cascade level
    flex: float = 0.0         # share of underflow surplus this item absorbs


@dataclass
class StackPlan:
    items: list[StackItem]
    heights: list[int]        # natural measured heights
    assigned: list[int]       # heights after flex distribution
    gaps: list[int]
    total: int                # sum(assigned) + sum(gaps)
    gap_level: float
    center_offset: int
    overflows: bool
    fill_ratio: float = field(default=0.0)


def item(kind: str, data: BaseModel, gap_before: float = 1.0,
         flex: float = 0.0) -> StackItem:
    return StackItem(get_component(kind), data, gap_before, flex)


def _gaps_at(items: list[StackItem], unit: int, level: float) -> list[int]:
    return [0 if i == 0 else round(it.gap_before * unit * level)
            for i, it in enumerate(items)]


def plan(items: list[StackItem], bbox: BBox, ctx: RenderContext,
         expand: bool = True) -> StackPlan:
    heights = [it.component.measure(it.data, bbox.w, ctx) for it in items]
    unit = ctx.theme.unit

    # -- compression path (overflow) --------------------------------------
    total = 0
    gaps: list[int] = []
    for level in GAP_LEVELS:
        gaps = _gaps_at(items, unit, level)
        total = sum(heights) + sum(gaps)
        if total <= bbox.h:
            break
    else:
        ctx.report.warn(
            f"stack overflow: content {total} EMU > zone {bbox.h} EMU even at "
            f"tightest gap level; components will truncate internally")
        p = StackPlan(items, heights, list(heights), gaps, total,
                      GAP_LEVELS[-1], 0, True)
        p.fill_ratio = 1.0
        return p

    assigned = list(heights)
    center = 0

    # -- expansion path (underflow) ----------------------------------------
    if expand and total < FILL_TARGET * bbox.h and len(items) > 0:
        surplus = bbox.h - total
        # 1) grow gaps toward GAP_EXPAND_MAX
        base_gaps = sum(_gaps_at(items, unit, 1.0))
        if base_gaps > 0 and level == 1.0:
            grow = min(surplus, round(base_gaps * (GAP_EXPAND_MAX - 1.0)))
            scale = 1.0 + grow / base_gaps
            gaps = [round(g * scale) for g in _gaps_at(items, unit, 1.0)]
            total = sum(heights) + sum(gaps)
            surplus = bbox.h - total
        # 2) distribute remaining surplus to flex items (capped growth)
        weights = [it.flex for it in items]
        if surplus > 0 and sum(weights) > 0:
            for i, it in enumerate(items):
                if it.flex <= 0:
                    continue
                share = round(surplus * it.flex / sum(weights))
                cap = round(heights[i] * FLEX_GROWTH_CAP)
                assigned[i] = heights[i] + min(share, cap)
            total = sum(assigned) + sum(gaps)
            surplus = bbox.h - total
        # 3) whatever remains: cap-centered block
        if surplus > 0:
            center = min(surplus // 2, CENTER_CAP)

    p = StackPlan(items, heights, assigned, gaps, total, level, center, False)
    p.fill_ratio = min(1.0, total / bbox.h) if bbox.h else 1.0
    return p


def render(slide, stack: StackPlan, bbox: BBox, ctx: RenderContext) -> int:
    cursor = bbox.y + stack.center_offset
    for it, natural, given, gap in zip(stack.items, stack.heights,
                                       stack.assigned, stack.gaps):
        cursor += gap
        avail = max(0, bbox.bottom - cursor)
        cell = BBox(bbox.x, cursor, bbox.w, min(given, avail) if avail else 0)
        if cell.h <= 0:
            ctx.report.warn(f"dropped component (no space): "
                            f"{type(it.data).__name__}")
            continue
        ctx.fill_hint = it.flex > 0
        try:
            consumed = it.component.render(slide, it.data, cell, ctx)
        finally:
            ctx.fill_hint = False
        if ctx.dev_assert and not stack.overflows:
            if it.flex > 0:
                if consumed > cell.h + ctx.theme.unit:
                    ctx.report.warn(
                        f"flex overrun in {type(it.data).__name__}: "
                        f"assigned {cell.h}, consumed {consumed}")
            elif abs(consumed - natural) > ctx.theme.unit:
                ctx.report.warn(
                    f"measure/render drift in {type(it.data).__name__}: "
                    f"measured {natural}, consumed {consumed}")
        cursor += max(consumed, given) if it.flex > 0 else consumed
    return cursor - bbox.y


def stack_into(slide, bbox: BBox, ctx: RenderContext,
               items: list[StackItem], record_fill: bool = True) -> int:
    """Plan + render in one call; records the zone fill ratio for eval."""
    p = plan(items, bbox, ctx)
    if record_fill and bbox.h > inch(2.0) and bbox.w > inch(5.0):
        # main body zones only — not title/footer strips or sidebars
        ctx.report.fills.append(round(p.fill_ratio, 3))
    return render(slide, p, bbox, ctx)

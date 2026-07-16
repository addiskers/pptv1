"""Two-phase vertical stacker.

Per the design review: layout is a pure function of (items, bbox, cascade level).
plan() measures everything and picks the gap-compression level as DATA; render()
then draws exactly once. No shape surgery, no eager drawing during planning.

v1 cascade: compress gaps (1.0 -> 0.75 -> 0.5) -> accept + warn (components
truncate internally and log to the BuildReport). Table splitting across slides is
a v1.1 concern; the seams (data_table.row_offsets) already exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from ..components.base import Component, RenderContext, get_component
from ..core.bbox import BBox

GAP_LEVELS = (1.0, 0.75, 0.5)


@dataclass
class StackItem:
    component: Component
    data: BaseModel
    gap_before: float = 1.0  # multiples of theme.unit, scaled by cascade level


@dataclass
class StackPlan:
    items: list[StackItem]
    heights: list[int]
    gaps: list[int]
    total: int
    gap_level: float
    overflows: bool


def item(kind: str, data: BaseModel, gap_before: float = 1.0) -> StackItem:
    return StackItem(get_component(kind), data, gap_before)


def plan(items: list[StackItem], bbox: BBox, ctx: RenderContext) -> StackPlan:
    heights = [it.component.measure(it.data, bbox.w, ctx) for it in items]
    for level in GAP_LEVELS:
        gaps = [0 if i == 0 else round(it.gap_before * ctx.theme.unit * level)
                for i, it in enumerate(items)]
        total = sum(heights) + sum(gaps)
        if total <= bbox.h:
            return StackPlan(items, heights, gaps, total, level, False)
    ctx.report.warn(
        f"stack overflow: content {total} EMU > zone {bbox.h} EMU even at "
        f"tightest gap level; components will truncate internally")
    return StackPlan(items, heights, gaps, total, GAP_LEVELS[-1], True)


def render(slide, stack: StackPlan, bbox: BBox, ctx: RenderContext) -> int:
    cursor = bbox.y
    for it, h, gap in zip(stack.items, stack.heights, stack.gaps):
        cursor += gap
        avail = max(0, bbox.bottom - cursor)
        cell = BBox(bbox.x, cursor, bbox.w, min(h, avail) if avail else 0)
        if cell.h <= 0:
            ctx.report.warn(f"dropped component (no space): "
                            f"{type(it.data).__name__}")
            continue
        consumed = it.component.render(slide, it.data, cell, ctx)
        if ctx.dev_assert and abs(consumed - h) > ctx.theme.unit and not stack.overflows:
            ctx.report.warn(
                f"measure/render drift in {type(it.data).__name__}: "
                f"measured {h}, consumed {consumed}")
        cursor += consumed
    return cursor - bbox.y


def stack_into(slide, bbox: BBox, ctx: RenderContext,
               items: list[StackItem]) -> int:
    """Convenience: plan + render in one call."""
    return render(slide, plan(items, bbox, ctx), bbox, ctx)

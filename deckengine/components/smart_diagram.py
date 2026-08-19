"""smart_diagram — REAL PowerPoint SmartArt via template cloning (opt-in).

THE one exemption from the measured-text contract: the graphicFrame is a
fixed box (height_in) and PowerPoint autofits the diagram inside it when
the file opens. Server previews (LibreOffice) show an empty frame — the
render warns so the note reaches the UI. Any clone failure falls back to
the equivalent DRAWN form (tree / cycle / hub_spoke): a deck never
breaks over SmartArt.
"""
from __future__ import annotations

from ..core.bbox import BBox
from ..core.units import inch
from ..schema.components import (CycleSpec, HubSpokeSpec, SmartDiagramSpec,
                                 SpokeSpec, TreeNodeSpec, TreeSpec)
from .base import Component, RenderContext, get_component, register


@register("smart_diagram")
class SmartDiagram(Component):
    spec_model = SmartDiagramSpec

    def measure(self, data: SmartDiagramSpec, width: int,
                ctx: RenderContext) -> int:
        return inch(data.height_in)

    def render(self, slide, data: SmartDiagramSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        total = inch(data.height_in)
        if ctx.fill_hint and bbox.h > total:
            total = bbox.h
        total = min(total, bbox.h) if bbox.h else total
        # per-layout hierarchy contract:
        # cycle -> flat ring; radial -> center + its spokes;
        # org/issue -> ONE root, branches nested under it, leaves under them
        if data.layout == "cycle":
            dropped = sum(len(n.children) for n in data.nodes)
            if dropped:
                ctx.report.warn(f"smart_diagram: cycle is flat; {dropped} "
                                "child node(s) ignored")
            nodes = [{"label": n.label} for n in data.nodes]
        elif data.layout == "radial":
            spokes = [{"label": n.label} for n in data.nodes[1:]]
            spokes += [{"label": c} for c in data.nodes[0].children]
            nodes = [{"label": data.nodes[0].label, "children": spokes}]
        else:  # org_chart / issue_tree
            root = data.nodes[0]
            branches = [{"label": n.label,
                         "children": [{"label": c} for c in n.children]}
                        for n in data.nodes[1:]]
            branches += [{"label": c} for c in root.children]
            nodes = [{"label": root.label, "children": branches}]
        try:
            from ..render.smartart_clone import add_smart_diagram
            add_smart_diagram(slide, data.layout, nodes, bbox.x, bbox.y,
                              bbox.w, total, ctx.theme.color("primary"))
            ctx.report.warn(
                "smart_diagram: SmartArt is laid out by PowerPoint — the "
                "server preview shows an empty frame; open the deck in "
                "PowerPoint to see and edit the diagram")
        except Exception as e:  # noqa: BLE001 — NEVER break a deck
            ctx.report.warn(f"smart_diagram: clone failed ({e}); "
                            f"rendering the drawn equivalent")
            return self._fallback(slide, data, bbox, total, ctx)
        return total

    def _fallback(self, slide, data: SmartDiagramSpec, bbox: BBox,
                  total: int, ctx: RenderContext) -> int:
        cell = BBox(bbox.x, bbox.y, bbox.w, total)
        if data.layout == "cycle":
            spec = CycleSpec(stages=[n.label for n in data.nodes][:8],
                             hub=None, highlight_index=None)
            return get_component("cycle").render(slide, spec, cell, ctx)
        if data.layout == "radial":
            spec = HubSpokeSpec(
                hub=data.nodes[0].label,
                spokes=[SpokeSpec(label=n.label)
                        for n in data.nodes[1:8]] or
                [SpokeSpec(label=data.nodes[0].label)] * 3)
            return get_component("hub_spoke").render(slide, spec, cell, ctx)
        variant = "org" if data.layout == "org_chart" else "issue"
        root = data.nodes[0]
        branches = [TreeNodeSpec(label=n.label,
                                 children=list(n.children)[:3])
                    for n in data.nodes[1:5]]
        if len(branches) < 2:  # tree needs >=2 branches; degrade further
            branches = branches + [TreeNodeSpec(label=c)
                                   for c in root.children[:3]]
        spec = TreeSpec(root=root.label, variant=variant,
                        children=branches[:4] or
                        [TreeNodeSpec(label=root.label)] * 2)
        return get_component("tree").render(slide, spec, cell, ctx)

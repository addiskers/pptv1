"""custom_layout assembler — render a bespoke composition tree into the body.

The root node gets the WHOLE body zone with fill_hint set: rows-with-fracs
allocates it by share, so bespoke slides fill the page like the hand-built
references instead of hugging the top.
"""
from __future__ import annotations

from ..components.base import RenderContext, get_component
from ..layout.stacker import item, stack_into
from ..schema.components import SectionHeaderSpec, TextBlockSpec
from ..schema.slide_types import CustomLayoutSpec
from .base import SlideAssembler, register_slide


@register_slide("custom_layout")
class CustomLayout(SlideAssembler):
    def assemble(self, slide, spec: CustomLayoutSpec,
                 ctx: RenderContext) -> None:
        z = self.render_title(slide, spec, ctx)
        body = z["body"]
        if spec.footnote:
            fn = TextBlockSpec(text=spec.footnote, size_role="micro",
                               color_role="ink_muted")
            fn_comp = get_component("text_block")
            fn_h = fn_comp.measure(fn, body.w, ctx)
            fn_bb, body = body.take_bottom(fn_h + ctx.theme.spacing(0.6))
            fn_comp.render(slide, fn, fn_bb.take_bottom(fn_h)[0], ctx)

        root = spec.root
        comp = get_component(root.kind)
        ctx.fill_hint = True  # bespoke trees are meant to fill the zone
        try:
            consumed = comp.render(slide, root, body, ctx)
        finally:
            ctx.fill_hint = False
        if body.h > 0:
            ctx.report.fills.append(round(min(1.0, consumed / body.h), 3))

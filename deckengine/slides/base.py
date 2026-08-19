"""Slide assembler contract + registry. One assembler per archetype."""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..components.base import RenderContext, get_component
from ..core.bbox import BBox
from ..layout.zones import standard_zones
from ..schema.components import SectionHeaderSpec


class SlideAssembler(ABC):
    @abstractmethod
    def assemble(self, slide, spec: BaseModel, ctx: RenderContext) -> None: ...

    def zones(self, *, title_h: float = 1.0) -> dict[str, BBox]:
        return standard_zones(title_h=title_h)

    def render_title(self, slide, spec, ctx: RenderContext, *,
                     rule: bool = False) -> dict[str, BBox]:
        """THE shared title block: section_header rendered directly INTO the
        fixed title zone (fit shrinks to the 14pt floor, then ellipsizes and
        reports). The body zone starts at title_h regardless of how the
        title fit, so title/body overlap is structurally impossible.
        With a kicker (section eyebrow) the zone grows 0.18in — kicker-gated,
        so kicker-less decks keep their exact geometry.
        """
        from ..schema.rich import strip_markers
        subtitle = getattr(spec, "subtitle", None)
        kicker = (getattr(spec, "kicker", None) or "").strip() or None
        title_h = 0.85 if not subtitle else 1.1
        if kicker:
            title_h += 0.18
        z = self.zones(title_h=title_h)
        # headlines drop provenance glyphs (they read as stray dots at
        # display size); the spec keeps its tokens for verification and
        # the methodology appendix
        get_component("section_header").render(
            slide, SectionHeaderSpec(title=strip_markers(spec.title),
                                     subtitle=(strip_markers(subtitle)
                                               if subtitle else None),
                                     kicker=kicker, rule=rule),
            z["title"], ctx)
        return z


_ASSEMBLERS: dict[str, SlideAssembler] = {}


def register_slide(slide_type: str):
    def deco(cls: type[SlideAssembler]) -> type[SlideAssembler]:
        _ASSEMBLERS[slide_type] = cls()
        return cls
    return deco


def get_assembler(slide_type: str) -> SlideAssembler:
    if slide_type not in _ASSEMBLERS:
        raise KeyError(f"no assembler for slide_type={slide_type!r}")
    return _ASSEMBLERS[slide_type]

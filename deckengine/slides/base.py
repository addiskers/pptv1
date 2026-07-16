"""Slide assembler contract + registry. One assembler per archetype."""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..components.base import RenderContext
from ..core.bbox import BBox
from ..layout.zones import standard_zones


class SlideAssembler(ABC):
    @abstractmethod
    def assemble(self, slide, spec: BaseModel, ctx: RenderContext) -> None: ...

    def zones(self, *, title_h: float = 1.0) -> dict[str, BBox]:
        return standard_zones(title_h=title_h)


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

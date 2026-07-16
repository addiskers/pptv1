"""Component contract — FROZEN. Every component implements exactly this.

measure() plans (no side effects); render() draws and must consume the height
measure() predicted (shared test asserts equality within 1pt). Components never
draw outside their bbox and never touch absolute slide coordinates.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from pydantic import BaseModel

from ..core.bbox import BBox
from ..core.fit_text import TextMeasurer
from ..core.theme import Theme

log = logging.getLogger("deckengine")


@dataclass
class BuildReport:
    warnings: list[str] = field(default_factory=list)
    truncations: list[str] = field(default_factory=list)
    splits: list[str] = field(default_factory=list)
    fills: list[float] = field(default_factory=list)  # body-zone fill ratios

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        log.warning(msg)

    def truncated(self, where: str) -> None:
        self.truncations.append(where)
        log.warning("truncated: %s", where)


@dataclass
class RenderContext:
    theme: Theme
    measurer: TextMeasurer
    report: BuildReport
    dev_assert: bool = True  # fail loudly on contract violations in dev
    fill_hint: bool = False  # set by the stacker around flexed renders ONLY:
    #                          components may stretch to bbox.h when True

    def font(self, role: str) -> str:
        return self.theme.font_display if role == "display" else self.theme.font_body

    def size(self, role: str) -> float:
        return getattr(self.theme, f"size_{role}")


class Component(ABC):
    """Stateless renderer for one spec model type."""

    spec_model: ClassVar[type[BaseModel]]

    @abstractmethod
    def measure(self, data: BaseModel, width: int, ctx: RenderContext) -> int:
        """Height (EMU) this component WOULD consume at `width`. No side effects."""

    @abstractmethod
    def render(self, slide, data: BaseModel, bbox: BBox, ctx: RenderContext) -> int:
        """Draw into slide within bbox. Return actual consumed height (EMU)."""


_REGISTRY: dict[str, Component] = {}


def register(kind: str):
    def deco(cls: type[Component]) -> type[Component]:
        _REGISTRY[kind] = cls()
        return cls
    return deco


def get_component(kind: str) -> Component:
    if kind not in _REGISTRY:
        raise KeyError(f"no component registered for kind={kind!r}")
    return _REGISTRY[kind]


def all_components() -> dict[str, Component]:
    return dict(_REGISTRY)

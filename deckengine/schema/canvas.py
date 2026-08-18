"""The Canvas — freeform slide design with the engine as safety net.

The designer pivot's core: instead of picking an archetype, the LLM places
ANY element anywhere on the slide (fractional geometry), and the engine
guarantees the result — every text element passes through fit_text into its
box (overflow structurally impossible), components clamp into their cells,
and deterministic rails (llm/canvas_rules.py) catch overlap/contrast/sliver
defects and feed the repair loop.

Geometry is in slide fractions (0..1). With render_title=True (default),
fractions address the BODY zone below the standard kicker/title block; with
render_title=False the designer owns the FULL slide surface (cover-style
designs) and must place the headline as an element.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from .base import SpeakerNotes
from .components import ComponentSpec, RichStr, coerce_role

MAX_ELEMENTS = 40
MIN_FRAC_W = 0.02
MIN_FRAC_H = 0.015
_EDGE_TOL = 0.005  # x+w may exceed 1.0 by at most this (float slack)

# an invented color role coerces to a legal default, never crashes a
# render (repair-trap discipline; seen live: fill_role='safe' raised
# KeyError mid-render and killed a whole variant)
InkRole = Annotated[str, BeforeValidator(coerce_role("ink"))]
FillRole = Annotated[str | None, BeforeValidator(coerce_role("surface"))]
LineRole = Annotated[str | None, BeforeValidator(coerce_role("grid"))]


class CanvasTextSpec(BaseModel):
    """Free text at any size — hero numbers, standfirsts, labels, kickers."""
    kind: Literal["canvas_text"] = "canvas_text"
    text: RichStr = Field(max_length=400)
    # explicit point size for display type (hero stats); None -> size_role
    size_pt: float | None = Field(default=None, ge=7, le=80)
    size_role: Literal["title", "h2", "stat", "body", "small",
                       "micro", "kicker"] = "body"
    color_role: InkRole = "ink"
    font: Literal["body", "display"] = "body"
    align: Literal["left", "center", "right"] = "left"
    anchor: Literal["top", "middle", "bottom"] = "top"
    caps: bool = False  # small-caps kicker treatment (letter-spaced)


class CanvasShapeSpec(BaseModel):
    """A themed shape, optionally carrying a centered label (panel/chip/band).
    A label-less shape behind other elements is a PANEL (legal to overlap)."""
    kind: Literal["canvas_shape"] = "canvas_shape"
    shape: Literal["rect", "rounded", "oval", "pentagon", "chevron",
                   "right_arrow", "down_arrow"] = "rect"
    fill_role: FillRole = "surface"
    line_role: LineRole = None
    line_w_pt: float = Field(default=0.75, ge=0.25, le=4)
    corner_radius: float = Field(default=0.15, ge=0, le=0.5)
    shadow: bool = False
    label: RichStr | None = Field(default=None, max_length=160)
    label_size_role: Literal["title", "h2", "stat", "body", "small",
                             "micro"] = "small"
    label_color_role: InkRole = "ink"


class CanvasLineSpec(BaseModel):
    """Axis-aligned rule/divider drawn through the element box's center."""
    kind: Literal["canvas_line"] = "canvas_line"
    direction: Literal["h", "v"] = "h"
    role: Annotated[str, BeforeValidator(coerce_role("grid"))] = "grid"
    weight_pt: float = Field(default=0.75, ge=0.25, le=4)
    dash: Literal["dash", "sysDot"] | None = None


CanvasContent = Annotated[
    Union[CanvasTextSpec, CanvasShapeSpec, CanvasLineSpec, ComponentSpec],
    Field(discriminator="kind"),
]


class CanvasElement(BaseModel):
    """One placed element: fractional geometry + paint order + content."""
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    w: float = Field(ge=MIN_FRAC_W, le=1)
    h: float = Field(ge=MIN_FRAC_H, le=1)
    z: int = Field(default=0, ge=-5, le=20)  # lower paints first
    content: CanvasContent

    @model_validator(mode="after")
    def _inside_slide(self):
        if self.x + self.w > 1 + _EDGE_TOL:
            raise ValueError(
                f"element right edge at {self.x + self.w:.3f} runs off the "
                f"slide: reduce x or w so x+w <= 1.0")
        if self.y + self.h > 1 + _EDGE_TOL:
            raise ValueError(
                f"element bottom edge at {self.y + self.h:.3f} runs off the "
                f"slide: reduce y or h so y+h <= 1.0")
        return self


class CanvasSlideSpec(SpeakerNotes):
    """A freeform-designed slide. `title` is the slide's CLAIM (drives
    checks, prior-slide context and the slide list); with
    render_title=False the designer must also PLACE the headline as a
    canvas_text element of at least h2 size."""
    slide_type: Literal["canvas"] = "canvas"
    title: RichStr = Field(max_length=220)
    subtitle: RichStr | None = Field(default=None, max_length=400)
    kicker: str | None = Field(default=None, max_length=40)
    render_title: bool = True
    # full-surface wash painted first (unknown roles coerce to None: a bad
    # bg guess should just mean "no wash", not a surprise surface fill)
    bg_fill_role: Annotated[
        str | None, BeforeValidator(coerce_role(None))] = None
    elements: list[CanvasElement] = Field(min_length=2,
                                          max_length=MAX_ELEMENTS)
    footnote: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _full_slide_needs_headline(self):
        if not self.render_title:
            big = any(
                el.content.kind == "canvas_text"
                and ((el.content.size_pt or 0) >= 14
                     or el.content.size_role in ("title", "h2"))
                for el in self.elements)
            if not big:
                raise ValueError(
                    "render_title=false means the design owns the headline: "
                    "add a canvas_text element with size_role='title' or "
                    "'h2' (or size_pt >= 14), or set render_title=true")
        return self

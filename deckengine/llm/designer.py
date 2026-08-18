"""The designer chain — brief → freeform design → judged selection.

Claude-class variety comes from three mechanisms here:
1. A tiny DESIGN BRIEF call before each canvas emission: the model decides
   what the eye must land on and names a layout concept BEFORE writing
   geometry (designers sketch intent first; so does the engine).
2. Silhouette memory: every slide's layout reduces to a grid-quantized
   signature; recent signatures ride into the next brief ("design
   differently") and identical-to-previous silhouettes lose points in the
   deterministic candidate score.
3. Candidate 2 is always briefed toward a DIFFERENT concept, so the judge
   compares genuinely distinct designs, not two drafts of one idea.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger("deckengine")

_GRID = 4  # quantization: a 4x4 grid is coarse enough to call two layouts "same"


class DesignBrief(BaseModel):
    """What the slide must DO visually, decided before any geometry."""
    message: str = Field(max_length=200, description=(
        "the one-sentence takeaway a viewer keeps"))
    eye_lands_on: str = Field(max_length=120, description=(
        "the ONE element seen first (a number, a bar, a word) — everything "
        "else supports it"))
    emphasis_entity: str | None = Field(default=None, max_length=40,
                                        description=(
        "the named subject to visually mark (row/bar/column), or null"))
    layout_concept: str = Field(max_length=100, description=(
        "3-8 words naming the composition, e.g. 'hero stat left, proof "
        "chart right, chips below'"))
    density: Literal["airy", "balanced", "dense"] = "balanced"


def brief_prompt(claim: str, visual_concept: str | None,
                 recent_silhouettes: list[str], has_facts: bool) -> str:
    lines = [
        "You are the slide DESIGNER. Before any layout is drawn, decide "
        "what this slide must do visually.",
        f"\nSlide claim (the title it must prove): {claim}",
    ]
    if visual_concept:
        lines.append(f"Outline's visual concept (refine or overrule): "
                     f"{visual_concept}")
    if recent_silhouettes:
        lines.append(
            f"The last {len(recent_silhouettes)} slides already used these "
            f"layout silhouettes — your concept MUST read differently on "
            f"the page: {'; '.join(recent_silhouettes[-4:])}")
    lines.append(
        "Numbers policy: " + ("use only provided FACTS." if has_facts else
                              "best real-world figures with provenance "
                              "markers."))
    lines.append(
        "\nEmit the design brief. The eye_lands_on element gets the "
        "biggest visual weight; if the claim names one entity among peers, "
        "set emphasis_entity to it.")
    return "\n".join(lines)


class DeckBriefs(BaseModel):
    """All body-slide briefs assigned in ONE call (T5.6): the designer sees
    every claim at once, so variety is decided globally upfront — stronger
    than the per-slide rolling memory it replaces."""
    briefs: list[DesignBrief]


def batch_brief_prompt(items: list[tuple[str, str | None, str | None]],
                       has_facts: bool) -> str:
    """items: (claim, visual_concept, section) per designed body slide."""
    lines = [
        "You are the deck's DESIGNER. Assign EVERY body slide its design "
        "brief now, all together — you can see the whole argument. Give "
        "each slide a DISTINCT layout_concept: no two ADJACENT slides may "
        "share a concept or read as the same silhouette on the page, and "
        "across the deck rotate treatments (hero-stat, chart-led, "
        "table-led, panel matrix, split, full-bleed band) so no design "
        "repeats before three slides have passed.",
        "Numbers policy: " + ("use only provided FACTS." if has_facts else
                              "best real-world figures with provenance "
                              "markers."),
        f"\nEmit exactly {len(items)} briefs, one per slide, in this order:"]
    for i, (claim, vc, section) in enumerate(items, start=1):
        s = f"\nSLIDE {i}"
        if section:
            s += f" [{section}]"
        s += f": {claim}"
        if vc:
            s += f"\n  outline's visual concept (refine or overrule): {vc}"
        lines.append(s)
    return "\n".join(lines)


# -- silhouette memory --------------------------------------------------------

def silhouette(slide) -> str:
    """Grid-quantized layout signature. Canvas slides reduce to their
    element map (kind-class + 4x4-grid geometry); archetype slides reduce
    to their slide_type (one mold = one look)."""
    if getattr(slide, "slide_type", "") != "canvas":
        return getattr(slide, "slide_type", "?")
    toks = []
    for el in slide.elements:
        k = el.content.kind
        cls = ("T" if k == "canvas_text" else
               "S" if k == "canvas_shape" else
               "L" if k == "canvas_line" else "C")
        toks.append(f"{cls}{round(el.x * _GRID)}{round(el.y * _GRID)}"
                    f"{round(el.w * _GRID)}{round(el.h * _GRID)}")
    return "canvas:" + ",".join(sorted(toks))


def describe_silhouette(sig: str) -> str:
    """Human-readable-ish form for prompts (the raw signature is noise to
    an LLM; a coarse description steers better)."""
    if not sig.startswith("canvas:"):
        return sig
    toks = sig[len("canvas:"):].split(",")
    n_t = sum(1 for t in toks if t.startswith("T"))
    n_c = sum(1 for t in toks if t.startswith("C"))
    n_s = sum(1 for t in toks if t.startswith("S"))
    return f"canvas({n_t} text/{n_c} component/{n_s} shape)"

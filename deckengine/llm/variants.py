"""The variant batch — one brief, N genuinely different decks.

Diversity is decided structurally and globally, before any deck is built:
one call assigns every variant a DISTINCT narrative flow (from
narrative.FLOWS) plus a one-sentence strategic angle. A different flow
forces a different section grammar (options_decision vs pyramid vs
benchmark read nothing alike), which is a far stronger diversity lever
than asking N independent generations to "be different" after the fact —
the same principle T5.6's batch design-briefs proved at the slide level,
applied here at the deck level.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

log = logging.getLogger("deckengine")


# the design personalities a variant can lean into — assigned DISTINCTLY
# across a batch so variant 2 isn't just a different argument, its slides
# are BUILT differently (each line is a full directive the designer reads)
DESIGN_LANGUAGES = {
    "hero_stat_editorial": (
        "hero-stat editorial: every body slide leads with ONE oversized "
        "number or claim as the dominant element; evidence supports in a "
        "quiet rail; generous whitespace"),
    "chart_forward_exhibit": (
        "chart-forward exhibit: the chart IS the slide — full-width "
        "exhibits, minimal prose, annotations and callouts do the talking"),
    "dark_panel_statement": (
        "dark panel statement: bold primary_dark panels and bands anchor "
        "every composition; inverse_ink typography; high contrast blocks"),
    "light_minimal_airy": (
        "light minimal airy: few elements, small refined typography, thin "
        "rules, wide margins — restraint as the design statement"),
    "table_led_dense": (
        "table-led dense: evidence-dense tables and comparison grids "
        "carry the argument; every slide reads like a working session"),
    "diagram_led_frameworks": (
        "diagram-led frameworks: 2x2s, funnels, pyramids, flows and "
        "chevrons structure every argument visually"),
}


class DeckAngle(BaseModel):
    flow_id: str = Field(description=(
        "one id from the flow menu, e.g. 'options_decision', 'pyramid'"))
    angle: str = Field(max_length=160, description=(
        "one-sentence distinct strategic framing for this variant"))
    emphasis_seed: str = Field(max_length=160, description=(
        "a hint folded into this variant's outline prompt — what this "
        "take emphasizes that the others don't"))
    design_language: str = Field(default="", description=(
        "one key from the design-language menu — DISTINCT per variant"))


class DeckAngles(BaseModel):
    angles: list[DeckAngle]


def angle_prompt(prompt: str, n: int) -> str:
    from .narrative import flow_menu
    return (
        f"You are planning {n} DIFFERENT decks from the SAME brief below "
        f"— alternative takes a partner could choose between, not {n} "
        "copies.\n\n"
        f"THE BRIEF:\n{prompt}\n\n"
        f"Assign each of the {n} variants a DIFFERENT flow — the flow is "
        "chosen by a DIFFERENT audience meta-question, which forces a "
        "genuinely different argument structure, not just different "
        "wording:\n" + flow_menu() + "\n\n"
        "Also assign each variant a DISTINCT design_language (one key per "
        "variant, no repeats) so the decks LOOK as different as they "
        "argue:\n"
        + "\n".join(f"- {k}: {v}" for k, v in DESIGN_LANGUAGES.items())
        + "\n\n"
        f"Emit exactly {n} angles, each with a distinct flow_id, a "
        "one-sentence angle (the strategic framing this variant takes), "
        "an emphasis_seed naming what THIS variant leads with that "
        "the others don't (a different metric, risk, or opportunity "
        "within the same brief), and its design_language key.")


def fallback_angles(n: int) -> list[DeckAngle]:
    """Deterministic, zero-LLM diversity floor: round-robin n distinct
    flow ids AND n distinct design languages straight from the
    registries. Always produces n structurally distinct angles even if
    the LLM call never runs."""
    from .narrative import FLOWS
    ids = list(FLOWS)
    langs = list(DESIGN_LANGUAGES)
    return [DeckAngle(flow_id=ids[i % len(ids)],
                      angle=f"Variant {i + 1}: argue the brief via the "
                            f"'{ids[i % len(ids)]}' flow.",
                      emphasis_seed="",
                      design_language=langs[i % len(langs)])
            for i in range(n)]


def design_directive(language: str) -> str | None:
    """The deck-level style block for a variant's design_language; None
    for unknown/empty keys (single-deck generation stays unstyled)."""
    text = DESIGN_LANGUAGES.get(language)
    return text


# opt-in (request.smartart): diagram slides use REAL PowerPoint SmartArt
# instead of the engine's drawn forms — clients who edit via the SmartArt
# UI asked for this; the trade-off (no server preview of the diagram) is
# stated wherever the toggle appears.
SMARTART_DIRECTIVE = (
    "The client wants PowerPoint SmartArt: whenever a slide's message is a "
    "cycle/flywheel, an org or issue hierarchy, or a hub-and-spoke, use a "
    "smart_diagram leaf (layout: cycle | org_chart | issue_tree | radial, "
    "nodes with children for hierarchy) INSTEAD of the drawn cycle/tree/"
    "hub_spoke components. Mention in the speaker notes that the diagram "
    "is editable via PowerPoint's SmartArt tools.")

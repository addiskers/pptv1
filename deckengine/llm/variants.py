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


class DeckAngle(BaseModel):
    flow_id: str = Field(description=(
        "one id from the flow menu, e.g. 'options_decision', 'pyramid'"))
    angle: str = Field(max_length=160, description=(
        "one-sentence distinct strategic framing for this variant"))
    emphasis_seed: str = Field(max_length=160, description=(
        "a hint folded into this variant's outline prompt — what this "
        "take emphasizes that the others don't"))


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
        f"Emit exactly {n} angles, each with a distinct flow_id, a "
        "one-sentence angle (the strategic framing this variant takes), "
        "and an emphasis_seed naming what THIS variant leads with that "
        "the others don't (a different metric, risk, or opportunity "
        "within the same brief).")


def fallback_angles(n: int) -> list[DeckAngle]:
    """Deterministic, zero-LLM diversity floor: round-robin n distinct
    flow ids straight from the registry. Always produces n structurally
    distinct angles even if the LLM call never runs."""
    from .narrative import FLOWS
    ids = list(FLOWS)
    return [DeckAngle(flow_id=ids[i % len(ids)],
                      angle=f"Variant {i + 1}: argue the brief via the "
                            f"'{ids[i % len(ids)]}' flow.",
                      emphasis_seed="")
            for i in range(n)]

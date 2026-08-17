"""ONE pairwise vision-judge call (Q4).

The engine generates 2-3 candidate specs per slide, renders all (seconds,
deterministic) and scores them with free metrics; the judge is called ONLY
when the deterministic score can't separate the finalists. Claude-style
generators write blind and stop at "good enough" — we look and choose.

Provider-pluggable like spec_generator: OpenAI or Anthropic, same model id.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

log = logging.getLogger("deckengine")

RUBRIC = """You are a DESIGN DIRECTOR choosing between two candidate renderings (A and B) of the SAME slide. The slide's claim: {claim}

Pick the one a top consulting firm would ship. Judge ONLY what you can see:
- visual hierarchy: does the eye land on the claim's proof FIRST, at the greatest visual weight?
- emphasis: is the claim's subject visually marked (color, size, position) — not merely stated?
- whitespace & alignment: shared edges, breathing room, no dead zones, no crowding
- structure fit: does the layout SHAPE match the argument (comparison, flow, ranking, part-of-whole)?
- distinctiveness: reward a composed, bespoke design over a stamped template look
- craft: consistent type sizes, readable contrast, emphasis discipline

Answer with the winner letter and one short reason."""


def _png_b64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("ascii")


def _craft_checklist() -> str:
    """Corpus-mined craft markers appended to the rubric (empty until a
    corpus run exists; text-only by design — no anchor images)."""
    from .style_priors import load_priors
    items = load_priors().get("judge_craft_checklist") or []
    if not isinstance(items, list) or not items:
        return ""
    lines = [str(x) for x in items[:6]]
    return ("\n\nTop-firm craft markers — reward the candidate that shows "
            "them:\n" + "\n".join(f"- {x}" for x in lines))


def pairwise_judge(png_a: Path, png_b: Path, claim: str) -> tuple[str, str]:
    """Return ("A"|"B", reason). Raises on provider errors — callers fall
    back to the deterministic score."""
    from .spec_generator import model_id, provider
    prompt = RUBRIC.format(claim=claim) + _craft_checklist()
    if provider() == "openai":
        from openai import OpenAI
        client = OpenAI()
        # generous cap: reasoning models spend completion tokens thinking
        resp = client.chat.completions.create(
            model=model_id(), max_completion_tokens=4000,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt + '\nRespond ONLY with JSON '
                 '{"winner": "A"|"B", "reason": "..."}.'},
                {"type": "text", "text": "Candidate A:"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + _png_b64(png_a)}},
                {"type": "text", "text": "Candidate B:"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + _png_b64(png_b)}},
            ]}])
        raw = json.loads(resp.choices[0].message.content)
    else:
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model_id(), max_tokens=300,
            tools=[{"name": "pick_winner", "description": "Pick the winner.",
                    "input_schema": {"type": "object", "properties": {
                        "winner": {"type": "string", "enum": ["A", "B"]},
                        "reason": {"type": "string"}},
                        "required": ["winner", "reason"]}}],
            tool_choice={"type": "tool", "name": "pick_winner"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "text", "text": "Candidate A:"},
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png",
                                             "data": _png_b64(png_a)}},
                {"type": "text", "text": "Candidate B:"},
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png",
                                             "data": _png_b64(png_b)}},
            ]}])
        raw = next(b.input for b in resp.content if b.type == "tool_use")
    winner = str(raw.get("winner", "A")).strip().upper()[:1]
    if winner not in ("A", "B"):
        winner = "A"
    return winner, str(raw.get("reason", ""))

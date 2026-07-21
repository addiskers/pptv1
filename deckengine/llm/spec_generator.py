"""Two-stage LLM spec generation. Provider-pluggable: OpenAI or Anthropic.

Stage 1: outline (slide_type + intent per slide) — narrative arc first.
Stage 2: one call per slide, structured output against the archetype's JSON
         schema, Pydantic-validated with a repair loop.

Provider selection: DECKENGINE_PROVIDER=openai|anthropic, else auto-detected
from OPENAI_API_KEY / ANTHROPIC_API_KEY. Model via DECKENGINE_MODEL.

Numbers: the fact table rides in every stage-2 prompt and
verify_spec_numbers() gates the result — the LLM never does arithmetic.
"""
from __future__ import annotations

import json
import logging
import os
from typing import get_args

from pydantic import BaseModel, ValidationError

from ..schema.slide_types import DeckMeta, DeckSpec, SlideSpec
from .facts import FactTable, verify_spec_numbers
from .story import REVIEW_PROMPT, Outline, check_outline

log = logging.getLogger("deckengine")

MAX_REPAIRS = 2
DEFAULTS = {"openai": "gpt-5.4", "anthropic": "claude-sonnet-5"}

_ARCHETYPES: dict[str, type[BaseModel]] = {
    m.model_fields["slide_type"].default: m for m in get_args(get_args(SlideSpec)[0])
}

SYSTEM = """You write slide specs for DeckEngine, a consulting-grade deck engine.
Hard rules:
- Titles are full-sentence takeaways ("X raised incomes 5% above state average"), never labels ("Results"). Keep titles under 160 characters.
- Prefer stats, tables and comparisons over prose (assertion-evidence style).
- Use ONLY numbers given in the FACTS block, with their display strings verbatim. Never compute, extrapolate or invent a number. If no FACTS block is given, use round illustrative numbers and mark the footnote 'illustrative data'.
- Rich text markup: **bold** for emphasis on numbers/leads, *italic* sparingly.
- Keep text tight: this engine renders at consulting density; long text gets shrunk then truncated.
- Respect every field constraint in the schema exactly."""


def provider() -> str:
    p = os.environ.get("DECKENGINE_PROVIDER")
    if p:
        return p
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    raise RuntimeError(
        "No LLM key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY.")


def model_id() -> str:
    return os.environ.get("DECKENGINE_MODEL", DEFAULTS[provider()])


def _structured_call(name: str, schema: dict, prompt: str,
                     max_tokens: int = 16000) -> dict:
    """One structured-output call, provider-dispatched. Returns the raw dict."""
    if provider() == "openai":
        from openai import OpenAI
        client = OpenAI()
        system = (SYSTEM + "\n\nRespond ONLY with a single JSON object (no prose, "
                  "no markdown fences) that validates against this JSON Schema:\n"
                  + json.dumps(schema))
        resp = client.chat.completions.create(
            model=model_id(),
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}])
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("hit token limit mid-spec; raise max_tokens")
        return json.loads(choice.message.content)

    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model_id(), max_tokens=max_tokens, system=SYSTEM,
        tools=[{"name": name, "description": f"Emit the {name}.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": name},
        messages=[{"role": "user", "content": prompt}])
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens mid-spec; raise max_tokens")
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("model returned no tool_use block")


def generate_outline(prompt: str, facts: FactTable | None) -> Outline:
    """Stage 1: claim-chain outline (story.Outline), then ONE holistic review
    pass with the deterministic check_outline problems riding along. The
    revised outline is kept only if it doesn't score worse."""
    archetype_list = ", ".join(_ARCHETYPES)
    schema = Outline.model_json_schema()
    p = (f"Plan a slide deck for this request:\n\n{prompt}\n\n"
         f"Available slide_type values: {archetype_list}.\n"
         f"{facts.prompt_block() if facts else ''}\n"
         "Emit the outline as a CLAIM CHAIN: a one-sentence governing_thought "
         "(the deck's answer), plus one entry per slide with slide_type and "
         "claim — the full-sentence assertion that slide proves (it becomes "
         "the slide title; never a label). Read in sequence, the claims must "
         "prove the governing thought. Vary the archetypes — never more than "
         "two consecutive slides of the same slide_type. Open with a title "
         "slide; close with an exec_summary or kpi_dashboard when it fits.")
    outline = Outline.model_validate(_structured_call("emit_outline", schema, p))
    problems = check_outline(outline)
    review = REVIEW_PROMPT
    if problems:
        review += ("\n\nDeterministic checks flagged these problems — fix "
                   "all of them:\n" + "\n".join(f"- {x}" for x in problems))
    review += "\n\nOUTLINE:\n" + outline.model_dump_json(indent=2)
    try:
        revised = Outline.model_validate(
            _structured_call("emit_outline", schema, review))
        if len(check_outline(revised)) <= len(problems):
            outline = revised
    except (ValidationError, RuntimeError) as e:  # review is best-effort
        log.warning("outline review pass failed, keeping original: %s", e)
    return outline


_FEW_SHOTS_DIR = __import__("pathlib").Path(__file__).parent / "few_shots"


def _few_shot(archetype: str) -> str:
    """A curated gold spec of this archetype, injected as an exemplar —
    moves density and structure more than any critique pass."""
    p = _FEW_SHOTS_DIR / f"{archetype}.json"
    if not p.is_file():
        return ""
    return ("\n\nEXAMPLE of an excellent spec of this type (match its density "
            "and structure, NOT its topic or numbers):\n" +
            p.read_text(encoding="utf-8"))


def generate_slide(archetype: str, intent: str, prompt: str,
                   facts: FactTable | None,
                   prior_slides: list[str] | None = None) -> BaseModel:
    model_cls = _ARCHETYPES[archetype]
    schema = model_cls.model_json_schema()
    # cross-slide context: without it, slides duplicate each other's content
    prior = ""
    if prior_slides:
        prior = ("\n\nSlides ALREADY WRITTEN (do NOT repeat their content; "
                 "this slide must add something new):\n" +
                 "\n".join(f"- {t}" for t in prior_slides))
    base_prompt = (
        f"Deck request:\n{prompt}\n\n"
        f"{facts.prompt_block() if facts else ''}{prior}{_few_shot(archetype)}\n\n"
        f"Write the spec for ONE slide of type '{archetype}'. Slide intent: {intent}")
    attempt_prompt = base_prompt
    slide = None
    last_error = ""
    for attempt in range(MAX_REPAIRS + 1):
        raw = _structured_call(f"emit_{archetype}", schema, attempt_prompt)
        raw.setdefault("slide_type", archetype)
        try:
            slide = model_cls.model_validate(raw)
        except ValidationError as e:
            last_error = "; ".join(
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                for err in e.errors()[:4])
            log.warning("slide %s validation failed (attempt %d): %s",
                        archetype, attempt, last_error)
            attempt_prompt = (base_prompt +
                              f"\n\nYour previous attempt failed validation:\n{e}\n"
                              "Fix ONLY these issues and emit the full JSON again.")
            continue
        if facts:
            suspects = verify_spec_numbers(slide.model_dump_json(), facts)
            if suspects and attempt < MAX_REPAIRS:
                attempt_prompt = (base_prompt +
                                  f"\n\nThese numbers are NOT in the FACTS block: "
                                  f"{suspects}. Replace them with fact display "
                                  "values or remove them. Emit the full JSON again.")
                continue
            if suspects:
                log.warning("unverified numbers survived repairs: %s", suspects)
        return slide
    if slide is None:
        raise RuntimeError(f"slide {archetype} failed validation after "
                           f"{MAX_REPAIRS + 1} attempts — last errors: {last_error}")
    return slide


def generate_deck_spec(prompt: str, *, csv_text: str | None = None,
                       theme: str = "consulting_navy",
                       meta: DeckMeta | None = None,
                       outline: Outline | None = None) -> DeckSpec:
    """outline: pass a (human-approved/edited) claim chain to skip stage 1."""
    log.info("spec generation via %s (%s)", provider(), model_id())
    facts = FactTable.from_csv(csv_text) if csv_text else None
    if outline is None:
        outline = generate_outline(prompt, facts)
    log.info("outline: %s", [o.slide_type for o in outline.slides])
    deck_context = (f"{prompt}\n\nDeck governing thought: "
                    f"{outline.governing_thought}")
    slides = []
    prior: list[str] = []
    for item in outline.slides:
        if item.slide_type not in _ARCHETYPES:
            log.warning("skipping unknown archetype %r", item.slide_type)
            continue
        slide = generate_slide(item.slide_type, item.claim, deck_context,
                               facts, prior_slides=prior)
        slides.append(slide)
        title = getattr(slide, "title", None) or item.claim
        prior.append(f"[{item.slide_type}] {title}")
    if not slides:
        raise RuntimeError("model produced no usable slides")
    if facts:
        appendix = sources_appendix(facts, slides)
        if appendix is not None:
            slides.append(appendix)
    return DeckSpec(theme=theme,
                    meta=meta or DeckMeta(title=prompt[:150]),
                    slides=slides)


def sources_appendix(facts: FactTable, slides: list[BaseModel]):
    """Auto-built (never LLM-written) appendix: every fact used in the deck
    with its value and provenance — the 'every number traceable' artifact."""
    from ..schema.slide_types import DataDeepDiveSpec
    spec_text = " ".join(s.model_dump_json() for s in slides)
    used = facts.used_facts(spec_text)
    if not used:
        return None
    rows = [[f.description[:78], f.display, (f.source or "provided data")[:70]]
            for f in used[:60]]
    return DataDeepDiveSpec(
        slide_type="data_deep_dive",
        title="Every number in this deck traces to source data",
        table={
            "kind": "data_table",
            "columns": [
                {"label": "Metric", "frac": 0.5},
                {"label": "Value", "frac": 0.14, "cell_kind": "number"},
                {"label": "Source", "frac": 0.36},
            ],
            "groups": [{"label": "Verified facts", "rows": rows}],
        },
        footnote="Auto-generated sources appendix. Values computed "
                 "deterministically from the provided data; the model cannot "
                 "introduce numbers outside this table.")

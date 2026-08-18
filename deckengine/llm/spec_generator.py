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

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ValidationError

from ..schema.slide_types import DeckMeta, DeckSpec, SlideSpec
from .facts import FactTable, verify_spec_numbers
from .format_rules import (check_outline_chart_density,
                           check_outline_formats, check_slide_format,
                           decision_table_text)
from .canvas_rules import check_canvas_slide
from .emphasis import check_slide_emphasis
from .exemplar_retrieval import select_exemplars
from .provenance import (append_legend_once, check_slide_markers,
                         inject_fact_markers, marker_coverage,
                         methodology_appendix)
from .story import REVIEW_PROMPT, Outline, check_outline
from .style_priors import prior_block
from .writing import check_slide_writing

log = logging.getLogger("deckengine")

MAX_REPAIRS = 2
DEFAULTS = {"openai": "gpt-5.4", "anthropic": "claude-sonnet-5"}
# simple structured decisions (briefs, outline review) run on a fast model;
# quality-critical calls (outline draft, slide emission, judge) never do
FAST_DEFAULTS = {"openai": "gpt-5.4-mini",
                 "anthropic": "claude-haiku-4-5-20251001"}

_ARCHETYPES: dict[str, type[BaseModel]] = {
    m.model_fields["slide_type"].default: m for m in get_args(get_args(SlideSpec)[0])
}

SYSTEM = """You are the slide DESIGNER for DeckEngine, a consulting-grade deck engine.
You design each slide AROUND its message — the fixed archetype molds are references, not menus. On 'canvas' slides you place every element freely (fractional geometry); make the ONE thing the viewer must see carry the greatest visual weight (size, color, position), and never give two adjacent slides the same silhouette.
Hard rules:
- Titles are full-sentence takeaways ("X raised incomes 5% above state average"), never labels ("Results"). Keep titles under 160 characters. A title carries a verb and, when the facts allow, a number.
- Prefer stats, tables and comparisons over prose (assertion-evidence style): every body element is EVIDENCE for the title claim, not commentary about it.
- With a FACTS block: use ONLY those numbers, display strings verbatim. Never compute, extrapolate or invent a number.
- WITHOUT a FACTS block: use the best real-world figures you actually know for this topic — named programs, real market sizes, real years. EVERY figure carries a provenance marker immediately after it: [[src:official]] for published/verified numbers, [[src:recon]] for numbers you reconstructed from known anchors, [[src:est]] for your own estimates. When unsure which tier applies, use [[src:est]]. The word "illustrative" is BANNED — a deck of placeholders has no argument. Chart series and table cells cannot carry markers; instead end that slide's footnote with the source, e.g. "Source: FAOSTAT 2025 [[src:official]]".
- Rich text markup: **bold** for emphasis on numbers/leads. *Italics* only for defined terms, at most twice per slide — italicising for tone is a machine tell.
- Writing craft: never hedge (may/might/could/potentially — state it or cut it). No exclamation marks. Never open a line with Additionally/Furthermore/Moreover. Vary sentence rhythm: a short punch, then longer support.
- Keep text tight: this engine renders at consulting density; long text gets shrunk then truncated.
- WORD BUDGET: dense body slides carry 140-180 words of real evidence (a winning deck averages ~164); dividers under 25. Under ~60 words reads as an empty slide; over 200 gets shrunk. Fill with evidence, never filler.
- SEMANTIC COLOUR: name chart series/categories with meaning-bearing words when the data has a health scale — the engine colours Overdrawn/Critical red, Moderate/Watch amber, Healthy/Safe green automatically.
- EMPHASIS: every comparative element visually marks the claim's subject — set highlight / highlight_row / highlight_column / highlight_index to the exact label of the entity the title names. A table proving "Indonesia is the best market" with no highlight on Indonesia is a broken slide. Leave emphasis null only when the title names no single entity.
- The subtitle is a STANDFIRST: one lede sentence that ADDS mechanism or so-what beyond the title — never a restatement of it.
- Every slide includes "notes": 2-3 DIRECTIVE speaker sentences (max 350 chars) — what to say, what to point at, what question to expect. Never a restatement of the slide text.
{principles}
- Respect every field constraint in the schema exactly."""

from .narrative import SLIDE_PRINCIPLES  # noqa: E402
SYSTEM = SYSTEM.replace("{principles}", SLIDE_PRINCIPLES)


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


def fast_model_id() -> str:
    return os.environ.get("DECKENGINE_FAST_MODEL", FAST_DEFAULTS[provider()])


def _structured_call(name: str, schema: dict, prompt: str,
                     max_tokens: int = 16000, model: str | None = None) -> dict:
    """One structured-output call, provider-dispatched, with transient-error
    retries (a network blip must never kill a 20-slide generation).
    model: an explicit model id, or the sentinel 'fast' resolved lazily to
    fast_model_id() at call time (lazy so mocked tests never need a key)."""
    import time as _time
    last: Exception | None = None
    for attempt in range(3):
        try:
            return _structured_call_once(name, schema, prompt, max_tokens,
                                         model)
        except (json.JSONDecodeError, RuntimeError):
            raise  # real model failures go to the repair loop, not a retry
        except Exception as e:  # noqa: BLE001 — connection/rate-limit class
            last = e
            log.warning("LLM call failed (attempt %d/3): %s", attempt + 1, e)
            _time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM unreachable after 3 attempts: {last}")


def _structured_call_once(name: str, schema: dict, prompt: str,
                          max_tokens: int = 16000,
                          model: str | None = None) -> dict:
    if model == "fast":
        model = fast_model_id()
    if provider() == "openai":
        from openai import OpenAI
        client = OpenAI()
        system = (SYSTEM + "\n\nRespond ONLY with a single JSON object (no prose, "
                  "no markdown fences) that validates against this JSON Schema:\n"
                  + json.dumps(schema))
        resp = client.chat.completions.create(
            model=model or model_id(),
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
        model=model or model_id(), max_tokens=max_tokens, system=SYSTEM,
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


def generate_outline(prompt: str, facts: FactTable | None,
                     forced_flow: str | None = None,
                     angle_hint: str | None = None) -> Outline:
    """Stage 1: claim-chain outline (story.Outline), then ONE holistic review
    pass with the deterministic check_outline problems riding along. The
    revised outline is kept only if it doesn't score worse.

    forced_flow/angle_hint: the variant batch (llm/variants.py) pins the
    flow instead of leaving the choice to the model, so N variants of one
    brief argue via N structurally different flows. narrative_arc is set
    from forced_flow in CODE after validation — never left to depend on
    the model actually complying with the instruction."""
    archetype_list = ", ".join(_ARCHETYPES)
    schema = Outline.model_json_schema()
    from .narrative import FLOWS, flow_menu
    if forced_flow and forced_flow in FLOWS:
        flow = FLOWS[forced_flow]
        flow_para = (
            f"The deck FLOW is FIXED: use '{flow.id}' — the audience asks "
            f"\"{flow.meta_question}\". Shape the claim chain to complete "
            "that flow's argument, closing on its ask/resolution."
            + (f" This variant's angle: {angle_hint}" if angle_hint else ""))
    else:
        flow_para = (
            "FIRST choose the deck FLOW by the AUDIENCE'S META-QUESTION — "
            "not the topic (the same data answers different questions with "
            "different decks). Declare it in narrative_arc and shape the "
            "claim chain to complete that flow's argument, closing on its "
            "ask/resolution:\n" + flow_menu())
    p = (f"Plan a slide deck for this request:\n\n{prompt}\n\n"
         f"Available slide_type values: {archetype_list}.\n"
         f"{facts.prompt_block() if facts else ''}\n"
         + flow_para + "\n\n"
         "Emit the outline as a CLAIM CHAIN: a one-sentence governing_thought "
         "(the deck's answer), plus one entry per slide with slide_type and "
         "claim — the full-sentence assertion that slide proves (it becomes "
         "the slide title; never a label). Give every BODY slide a 'section' "
         "tag: 2-4 words naming the act it belongs to (e.g. 'THE "
         "OPPORTUNITY', 'WHAT IT TAKES') — identical across consecutive "
         "slides of one act, changing only at section boundaries; null on "
         "title and divider slides. Give every BODY slide a "
         "'visual_concept': one sentence naming its composition (form + "
         "arrangement, e.g. 'oversized stat left panel, evidence chart "
         "right, proof chips below') — every concept DIFFERENT from its "
         "neighbours; body slides are later DESIGNED freeform from these "
         "concepts. Read in sequence, the claims must "
         "prove the governing thought. VARY THE VISUAL RHYTHM so the deck "
         "never reads as stamped from a fixed set of molds: never more than "
         "two consecutive slides of the same slide_type, and use custom_layout "
         "LIBERALLY — aim for at least a quarter of the body slides (min 1-2) "
         "as bespoke custom_layout compositions (hero-stat + proof stack, a "
         "2x2 or 2x3 panel matrix, a chart + drivers split, an evidence pair "
         "of two charts, a table braced to its takeaway). Use custom_layout "
         "ALWAYS for prioritisation 2x2s, funnels, option scorecards or "
         "image-led slides: the matrix_2x2, funnel, harvey_balls and "
         "image_block components live only inside custom_layout trees. "
         "CHART DENSITY: the best decks CHART their data — put a native "
         "chart on at least 60% of data-bearing body slides (chart_slide, "
         "or a chart-embedding custom_layout such as an evidence pair or a "
         "chart + drivers split). When variety demands a different look, "
         "rotate the chart's HOME, never drop the chart. Open "
         "with a title slide; close with an exec_summary or kpi_dashboard "
         "when it fits.\n"
         + ("" if facts else
            "Because this deck runs on marked real-world figures rather than "
            "a provided dataset, the CLOSING exec_summary's last two sections "
            "must be exactly: 'What we would want to be challenged on' and "
            "'Where we are least confident' — honest, specific, tied to the "
            "deck's weakest numbers.\n")
         + "\n" + decision_table_text())
    outline = Outline.model_validate(_structured_call("emit_outline", schema, p))
    if forced_flow and forced_flow in FLOWS:
        outline.narrative_arc = forced_flow  # deterministic, not model trust

    def _problems(o: Outline) -> list[str]:
        from .narrative import check_outline_flow
        out = (check_outline(o) + check_outline_formats(o, facts)
               + check_outline_chart_density(o) + check_outline_flow(o))
        if not facts and not any(s.slide_type == "exec_summary"
                                 for s in o.slides):
            out.append(
                "a marker-mode deck MUST close with an exec_summary whose "
                "last two sections are 'What we would want to be challenged "
                "on' and 'Where we are least confident'")
        return out

    problems = _problems(outline)
    review = REVIEW_PROMPT
    if problems:
        review += ("\n\nDeterministic checks flagged these problems — fix "
                   "all of them:\n" + "\n".join(f"- {x}" for x in problems))
    review += "\n\nOUTLINE:\n" + outline.model_dump_json(indent=2)
    try:
        # the review is a structural edit kept only if it scores no worse —
        # the fast model is enough for it (the draft stays on the main model)
        revised = Outline.model_validate(
            _structured_call("emit_outline", schema, review,
                             model="fast"))
        if forced_flow and forced_flow in FLOWS:
            revised.narrative_arc = forced_flow
        if len(_problems(revised)) <= len(problems):
            outline = revised
    except (ValidationError, RuntimeError) as e:  # review is best-effort
        log.warning("outline review pass failed, keeping original: %s", e)
    return outline


_FEW_SHOTS_DIR = Path(__file__).parent / "few_shots"
WON_DIR = _FEW_SHOTS_DIR / "won"


def _fallback_picks(archetype: str, pool: list[Path], k: int) -> list[Path]:
    """Historical rule for when retrieval is off/empty: {archetype}_2.json
    then the latest won winner by mtime."""
    picks: list[Path] = []
    a2 = _FEW_SHOTS_DIR / f"{archetype}_2.json"
    if a2.is_file():
        picks.append(a2)
    won = sorted((p for p in pool if p.parent == WON_DIR),
                 key=lambda p: p.stat().st_mtime)
    if won:
        picks.append(won[-1])
    return picks[:k]


def _few_shot(archetype: str, claim: str = "") -> str:
    """Curated gold specs of this archetype, injected as exemplars — they
    move density and structure more than any critique pass. The canonical
    {archetype}.json is always kept as the mold; the remaining slots are the
    BEST-MATCHING exemplars for this claim (by claim_context / chart / craft
    / firm) drawn from the whole pool — hand-authored {archetype}_N.json,
    induced big-firm exemplars, and won/ winners — via exemplar_retrieval.
    Falls back to the historical mtime rule when retrieval is off. Max 3."""
    base = _FEW_SHOTS_DIR / f"{archetype}.json"
    paths: list[Path] = [base] if base.is_file() else []
    pool = sorted(_FEW_SHOTS_DIR.glob(f"{archetype}_*.json"))
    if WON_DIR.is_dir():
        pool += sorted(WON_DIR.glob(f"{archetype}_*.json"))
    k = max(0, 3 - len(paths))
    picks = select_exemplars(archetype, claim, pool, _FEW_SHOTS_DIR, k)
    if not picks:  # retrieval disabled or nothing loaded -> historical rule
        picks = _fallback_picks(archetype, pool, k)
    seen: set[Path] = set()
    ordered: list[Path] = []
    for p in paths + picks:
        if p not in seen and p.is_file():
            seen.add(p)
            ordered.append(p)
    ordered = ordered[:3]
    if not ordered:
        return ""
    return ("\n\nNOTE: examples may predate the provenance-marker and "
            "speaker-notes rules — your spec must still follow them."
            + "".join(
                f"\n\nEXAMPLE {i} of an excellent spec of this type (match "
                "its density and structure, NOT its topic or numbers):\n"
                + p.read_text(encoding="utf-8")
                for i, p in enumerate(ordered, start=1)))


_CANVAS_HELP = (
    "\n\nCANVAS DESIGN RULES: place elements with fractional x/y/w/h "
    "(0..1 of the body area below the title; of the FULL slide when "
    "render_title=false). Content kinds: canvas_text (size_pt up to 80 for "
    "hero numbers; caps=true for small-caps labels), canvas_shape "
    "(rect/rounded/oval/pentagon/chevron/right_arrow/down_arrow; optional "
    "centered label; a LABEL-LESS shape at lower z is a panel others sit "
    "on), canvas_line (h/v rule), or ANY component kind as a placeable "
    "primitive: native_chart, mini_table, bullet_list, stat_row, "
    "kpi_card_strip, funnel, matrix_2x2, harvey_balls, donut_stat, "
    "progress_pill, timeline_row, icon_stat_row, callout_band, "
    "brace_group. Use color_role='inverse_ink' for any text on dark fills. "
    "6-14 elements is the sweet spot. GRID DISCIPLINE: place on a "
    "12-column grid — x and w in multiples of 1/12 (0.083); a slide has "
    "AT MOST 4 distinct left edges; an indent is exactly one grid step; "
    "stack related elements on the SAME left edge. Compositions span the "
    "full height — no dead quadrants; one dominant element, everything "
    "else supports it.")


def generate_slide(archetype: str, intent: str, prompt: str,
                   facts: FactTable | None,
                   prior_slides: list[str] | None = None,
                   design_brief: str | None = None) -> BaseModel:
    model_cls = _ARCHETYPES[archetype]
    schema = model_cls.model_json_schema()
    # cross-slide context: without it, slides duplicate each other's content
    # (worded for parallel generation — the OTHER slides' claims, whether or
    # not they are written yet, fence off their arguments and evidence)
    prior = ""
    if prior_slides:
        prior = ("\n\nOTHER SLIDES IN THIS DECK — never make their argument "
                 "or reuse their headline evidence; prove ONLY this slide's "
                 "claim:\n" +
                 "\n".join(f"- {t}" for t in prior_slides))
    # teach the format decision table where the chart choice is live
    table = ("\n\n" + decision_table_text()
             if archetype in ("chart_slide", "custom_layout", "canvas")
             else "")
    if archetype == "canvas":
        table += _CANVAS_HELP
    if design_brief:
        table += "\n\n" + design_brief
    # corpus-mined style priors (empty until a corpus run has been done)
    priors = prior_block(archetype, intent)
    if priors:
        table += "\n\n" + priors
    base_prompt = (
        f"Deck request:\n{prompt}\n\n"
        f"{facts.prompt_block() if facts else ''}{prior}{_few_shot(archetype, intent)}"
        f"{table}\n\n"
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
        # ONE combined check pass (T5.6): every category's problems gather
        # into a single list and a single repair call fixes them all — the
        # per-category cascade cost up to 8+ sequential re-emits per slide
        problems: list[str] = []
        if facts:
            suspects = verify_spec_numbers(slide.model_dump_json(), facts)
            if suspects:
                problems.append(
                    f"[numbers] these numbers are NOT in the FACTS block: "
                    f"{suspects} — replace them with fact display values or "
                    f"remove them")
        else:
            # no-CSV mode: every figure must carry its provenance marker
            problems += [f"[provenance] {p}"
                         for p in check_slide_markers(slide)]
        problems += [f"[writing] {p}" for p in check_slide_writing(slide)]
        problems += [f"[format] {p}" for p in check_slide_format(slide, facts)]
        problems += [f"[emphasis] {p}" for p in check_slide_emphasis(slide)]
        if slide.slide_type == "canvas":
            problems += [f"[design] {p}" for p in check_canvas_slide(slide)]
        if not problems:
            return slide
        if attempt < MAX_REPAIRS:
            attempt_prompt = (base_prompt +
                              "\n\nProblems found — fix ALL of them at once "
                              "while keeping the same facts, claims and "
                              "layout intent:\n" +
                              "\n".join(f"- {p}" for p in problems) +
                              "\nEmit the full JSON again.")
            continue
        log.warning("problems survived repairs: %s", problems)
        return slide
    if slide is None:
        raise RuntimeError(f"slide {archetype} failed validation after "
                           f"{MAX_REPAIRS + 1} attempts — last errors: {last_error}")
    return slide


# --- multi-candidate + judge (Q4) -------------------------------------------

_VARIANT_NUDGE = ("\n\nVariant instruction: take a DIFFERENT structural "
                  "approach than the obvious one — a different component "
                  "mix, density or layout shape — while proving the same "
                  "claim with the same facts.")


def candidate_count() -> int:
    """2-3 candidates per slide by default (quality over cost, approved);
    DECKENGINE_CANDIDATES=1 is the cheap-mode opt-out."""
    try:
        n = int(os.environ.get("DECKENGINE_CANDIDATES", "2"))
    except ValueError:
        n = 2
    return max(1, min(3, n))


def _render_candidate(slide, theme: str, workdir: Path, tag: str) -> dict:
    """Free deterministic score: render the slide alone, read the report.
    A candidate that cannot render at all loses outright."""
    from ..render.deck_builder import build_deck
    out = workdir / f"{tag}.pptx"
    try:
        report = build_deck(DeckSpec(theme=theme,
                                     meta=DeckMeta(title="candidate"),
                                     slides=[slide]), out)
    except Exception as e:  # noqa: BLE001 — deterministic loss, not a crash
        log.warning("candidate %s failed to render: %s", tag, e)
        return {"defects": 999, "fill": 0.0, "pptx": None}
    return {"defects": len(report.warnings) + len(report.truncations),
            "fill": round(min(report.fills) if report.fills else 1.0, 3),
            "pptx": out}


def _export_png(pptx: Path) -> Path | None:
    try:  # provider seam; absence falls back to the deterministic pick
        from ..render.preview_provider import get_preview_exporter
        exporter = get_preview_exporter()
        if exporter is None:
            return None
        pngs = exporter(pptx, pptx.parent / (pptx.stem + "_png"),
                        width=1280, height=720)
        return pngs[0] if pngs else None
    except Exception as e:  # noqa: BLE001
        log.info("no preview available for judge (%s)", e)
        return None


def _record_win(archetype: str, slide) -> None:
    """Judge-picked winners join the gold-spec library — compounding
    few-shots (the latest win rides in every future stage-2 prompt)."""
    try:
        WON_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(
            slide.model_dump_json().encode("utf-8")).hexdigest()[:10]
        p = WON_DIR / f"{archetype}_{digest}.json"
        if not p.is_file():
            p.write_text(slide.model_dump_json(), encoding="utf-8")
    except OSError as e:
        log.warning("could not record win: %s", e)


def _design_brief(claim: str, visual_concept: str | None,
                  recent_silhouettes: list[str],
                  facts: FactTable | None) -> "DesignBrief | None":
    """One tiny structured call deciding the slide's visual intent BEFORE
    geometry. Best-effort: a failed brief never blocks generation."""
    from .designer import DesignBrief, brief_prompt, describe_silhouette
    try:
        raw = _structured_call(
            "design_brief", DesignBrief.model_json_schema(),
            brief_prompt(claim, visual_concept,
                         [describe_silhouette(s)
                          for s in recent_silhouettes[-4:]],
                         facts is not None),
            max_tokens=2000, model="fast")
        return DesignBrief.model_validate(raw)
    except Exception as e:  # noqa: BLE001
        log.warning("design brief failed (%s); designing without one", e)
        return None


def _batch_briefs(items: list[tuple[str, str | None, str | None]],
                  facts: FactTable | None) -> list | None:
    """ONE fast-model call assigns every designed slide's brief together —
    variety decided globally before any slide is written (T5.6). None on
    any failure: generate_slide_best falls back to per-slide briefs."""
    from .designer import DeckBriefs, batch_brief_prompt
    if not items:
        return []
    try:
        raw = _structured_call(
            "design_briefs", DeckBriefs.model_json_schema(),
            batch_brief_prompt(items, facts is not None),
            max_tokens=8000, model="fast")
        briefs = DeckBriefs.model_validate(raw).briefs
        if len(briefs) != len(items):
            log.warning("batch briefs returned %d briefs for %d slides; "
                        "falling back to per-slide briefs",
                        len(briefs), len(items))
            return None
        return list(briefs)
    except Exception as e:  # noqa: BLE001
        log.warning("batch briefs failed (%s); per-slide fallback", e)
        return None


def _brief_text(brief, alternate: bool) -> str:
    if brief is None:
        return ""
    head = ("DESIGN BRIEF — follow it exactly:" if not alternate else
            "DESIGN BRIEF — same message and emphasis, but take a "
            f"DIFFERENT layout concept than {brief.layout_concept!r}:")
    lines = [head,
             f"- message: {brief.message}",
             f"- the eye lands on: {brief.eye_lands_on} (give it the "
             f"greatest visual weight)"]
    if brief.emphasis_entity:
        lines.append(f"- visually mark: {brief.emphasis_entity}")
    if not alternate:
        lines.append(f"- layout concept: {brief.layout_concept}")
    lines.append(f"- density: {brief.density}")
    return "\n".join(lines)


class JudgeBudget:
    """Per-deck cap on vision-judge calls (T5.6): ties beyond the budget
    fall to the deterministic pick. Thread-safe — waves share one budget."""
    def __init__(self, n: int):
        import threading
        self.n = n
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.n <= 0:
                return False
            self.n -= 1
            return True


def judge_budget_default() -> int:
    try:
        return max(0, int(os.environ.get("DECKENGINE_JUDGE_BUDGET", "6")))
    except ValueError:
        return 6


# warnings that mean elements PHYSICALLY collide or paint beyond their box
# on the rendered slide — the class the render-truth repair chases. Marks
# must be ground truth only: the audit's measured text overlaps plus the
# self-reports of the few components that truly draw past their bbox.
# Density guesses ("tight in its box") and self-clamping notes ("clamping",
# "may clip") are NOT here — feeding unfixable problems to the repair
# poisoned its accept criterion (live finding: 11/11 repairs rejected).
_RENDER_MARKS = ("text overlap", "exceeds bbox",
                 "taller than provided bbox",
                 "row taller than provided bbox")
_RENDER_SKIP = ("clamping", "may clip")


def _render_problems(slide, theme: str) -> list[str]:
    """Render the slide solo (deterministic, no LLM) and return ALL its
    overlap/overflow warnings as repairable problem strings (uncapped —
    the accept criterion compares counts; the prompt caps separately)."""
    from ..render.deck_builder import build_deck
    workdir = Path(tempfile.mkdtemp(prefix="deckengine_rt_"))
    try:
        report = build_deck(DeckSpec(theme=theme,
                                     meta=DeckMeta(title="rt"),
                                     slides=[slide]),
                            workdir / "rt.pptx")
    except Exception as e:  # noqa: BLE001 — a non-rendering slide is the worst defect
        return [f"[render] the slide failed to render at all: {e}"]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return [f"[render] {w}" for w in report.warnings
            if any(m in w for m in _RENDER_MARKS)
            and not any(s in w for s in _RENDER_SKIP)]


def _maybe_render_repair(slide, claim: str, prompt: str,
                         facts: FactTable | None,
                         theme: str) -> BaseModel:
    """Render-truth repair: overlap/overflow measured on the ACTUAL render
    becomes ONE repair call (canvas only — archetype molds place
    deterministically). Fast mode's first-ever render feedback; best
    mode's fixer when every candidate rendered dirty. Deterministic
    accept: keep the repair only if it renders strictly cleaner.
    OPT-IN via DECKENGINE_RENDER_REPAIR=1: across 30+ live attempts the
    model never beat the deterministic layers (clamp contract, auto-grow,
    footnote reservation) — until the repair prompt earns its keep, the
    default skips the extra call per dirty slide."""
    if os.environ.get("DECKENGINE_RENDER_REPAIR", "0") != "1":
        return slide
    if getattr(slide, "slide_type", "") != "canvas":
        return slide
    probs = _render_problems(slide, theme)
    if not probs:
        return slide
    model_cls = _ARCHETYPES["canvas"]
    p = (f"Deck request:\n{prompt}\n\n"
         f"{facts.prompt_block() if facts else ''}"
         f"Slide claim: {claim}\n\n"
         "Your slide design below was RENDERED and measured — it has "
         "physical defects. Fix ALL of them while keeping the message: "
         "give each element enough height and width for its content, move "
         "colliding elements apart onto free canvas, and CUT content that "
         "cannot fit. Elements must never touch or spill onto neighbours."
         + _CANVAS_HELP + "\n\n"
         "CURRENT SPEC:\n" + slide.model_dump_json() + "\n\n"
         "MEASURED DEFECTS (from the actual render):\n"
         + "\n".join(f"- {x}" for x in probs[:8])
         + "\n\nEmit the full corrected JSON.")
    try:
        raw = _structured_call("emit_canvas", model_cls.model_json_schema(), p)
        raw.setdefault("slide_type", "canvas")
        fixed = model_cls.model_validate(raw)
    except Exception as e:  # noqa: BLE001 — repair is best-effort
        log.warning("render repair failed (%s); keeping original", e)
        return slide
    # accept on RENDER truth alone: strictly fewer measured defects. The
    # canvas rails are deliberately not re-checked here — fixing overlap
    # often means cutting/shrinking content, which trips the advisory
    # coverage rail and vetoed every good repair when it was a guard.
    fixed_probs = _render_problems(fixed, theme)
    if len(fixed_probs) < len(probs):
        log.info("render repair accepted (%d -> %d render defects)",
                 len(probs), len(fixed_probs))
        return fixed
    log.warning("render repair did not improve (render %d -> %d); "
                "keeping original", len(probs), len(fixed_probs))
    return slide


def generate_slide_best(archetype: str, claim: str, prompt: str,
                        facts: FactTable | None,
                        prior_slides: list[str] | None = None,
                        theme: str = "consulting_navy",
                        visual_concept: str | None = None,
                        recent_silhouettes: list[str] | None = None,
                        brief="auto", n_candidates: int | None = None,
                        judge_budget: JudgeBudget | None = None) -> BaseModel:
    """Candidate generation + judging (see _pick_slide_best), then the
    render-truth repair pass: the winner is rendered for real and any
    overlap/overflow it still carries becomes one final repair call."""
    slide = _pick_slide_best(
        archetype, claim, prompt, facts, prior_slides=prior_slides,
        theme=theme, visual_concept=visual_concept,
        recent_silhouettes=recent_silhouettes, brief=brief,
        n_candidates=n_candidates, judge_budget=judge_budget)
    return _maybe_render_repair(slide, claim, prompt, facts, theme)


def _pick_slide_best(archetype: str, claim: str, prompt: str,
                     facts: FactTable | None,
                     prior_slides: list[str] | None = None,
                     theme: str = "consulting_navy",
                     visual_concept: str | None = None,
                     recent_silhouettes: list[str] | None = None,
                     brief="auto", n_candidates: int | None = None,
                     judge_budget: JudgeBudget | None = None) -> BaseModel:
    """N candidates -> render all -> deterministic score -> ONE pairwise
    vision-judge call only when the metrics can't separate the finalists.
    Canvas slides get a DESIGN BRIEF first; candidate 2 is briefed toward a
    different concept, and a candidate whose silhouette repeats the
    previous slide's loses the tie.

    brief: 'auto' makes the per-slide brief call for canvas; a DesignBrief
    uses the batch pre-pass result; None designs without one."""
    from .designer import silhouette
    recent = recent_silhouettes or []
    prev_sil = recent[-1] if recent else None
    if archetype != "canvas":
        brief = None
    elif brief == "auto":
        brief = _design_brief(claim, visual_concept, recent, facts)
    n = (max(1, min(3, n_candidates)) if n_candidates
         else candidate_count())
    if n == 1:
        return generate_slide(archetype, claim, prompt, facts,
                              prior_slides=prior_slides,
                              design_brief=_brief_text(brief, False))
    cands = []
    for i in range(n):
        p = prompt if i == 0 else prompt + _VARIANT_NUDGE
        try:
            cands.append(generate_slide(
                archetype, claim, p, facts, prior_slides=prior_slides,
                design_brief=_brief_text(brief, alternate=i > 0)))
        except RuntimeError as e:
            log.warning("candidate %d for %s failed: %s", i, archetype, e)
    if not cands:
        raise RuntimeError(f"all {n} candidates failed for {archetype}")
    uniq, seen = [], set()
    for c in cands:
        key = c.model_dump_json()
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    if len(uniq) == 1:
        return uniq[0]

    workdir = Path(tempfile.mkdtemp(prefix="deckengine_cand_"))
    try:
        scored = [(c, _render_candidate(c, theme, workdir, f"cand{i}"))
                  for i, c in enumerate(uniq)]
        for c, s in scored:
            # repeating the previous slide's silhouette is a defect class:
            # variety is part of the score, not just the judge's taste
            s["same_sil"] = 1 if (prev_sil
                                  and silhouette(c) == prev_sil) else 0
        scored.sort(key=lambda cs: (cs[1]["defects"], cs[1]["same_sil"],
                                    -cs[1]["fill"]))
        best, runner = scored[0], scored[1]
        clear = (best[1]["defects"] < runner[1]["defects"]
                 or best[1]["same_sil"] < runner[1]["same_sil"]
                 or best[1]["fill"] - runner[1]["fill"] > 0.05)
        if clear or best[1]["pptx"] is None or runner[1]["pptx"] is None:
            return best[0]
        if judge_budget is not None and not judge_budget.take():
            return best[0]  # budget spent: deterministic pick
        png_a = _export_png(best[1]["pptx"])
        png_b = _export_png(runner[1]["pptx"])
        if png_a is None or png_b is None:
            return best[0]
        from .judge import pairwise_judge
        try:
            winner, reason = pairwise_judge(png_a, png_b, claim)
        except Exception as e:  # noqa: BLE001 — judge is best-effort
            log.warning("vision judge failed (%s); deterministic pick", e)
            return best[0]
        log.info("vision judge picked %s: %s", winner, reason)
        chosen = best[0] if winner == "A" else runner[0]
        _record_win(archetype, chosen)
        return chosen
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _wave_size() -> int:
    """Concurrent slide generations (T5.6). 4 balances wall-clock against
    provider rate limits; DECKENGINE_PARALLEL=1 restores sequential."""
    try:
        n = int(os.environ.get("DECKENGINE_PARALLEL", "4"))
    except ValueError:
        n = 4
    return max(1, min(8, n))


_MAX_SWEEP_REGENS = 3   # post-sweep regens are bounded: polish, not a loop

_NUM_RE = re.compile(r"\d[\d,.]*\d|\d")
_WORD_RE = re.compile(r"[a-z][a-z']{3,}")


def _title_sig(title: str) -> tuple[set[str], set[str]]:
    t = re.sub(r"\[\[src:[a-z]+\]\]", " ", title.lower())
    t = t.replace("**", " ").replace("*", " ")
    return set(_NUM_RE.findall(t)), set(_WORD_RE.findall(t))


def _dupe_pairs(titles: list[str]) -> list[tuple[int, int]]:
    """The content sweep's detector (deterministic, testable): pairs
    (i, j), i < j, whose titles argue the same thing — a shared headline
    figure plus half the content words, or near-identical wording. Each
    offender j is flagged once, against its earliest match."""
    sigs = [_title_sig(t) for t in titles]
    out: list[tuple[int, int]] = []
    for j in range(len(titles)):
        for i in range(j):
            ni, wi = sigs[i]
            nj, wj = sigs[j]
            if not wi or not wj:
                continue
            overlap = len(wi & wj) / min(len(wi), len(wj))
            if (ni & nj and overlap >= 0.5) or overlap >= 0.8:
                out.append((i, j))
                break
    return out


def generate_deck_spec(prompt: str, *, csv_text: str | None = None,
                       theme: str = "consulting_navy",
                       meta: DeckMeta | None = None,
                       outline: Outline | None = None,
                       quality: str = "best",
                       progress_cb=None,
                       design_directive: str | None = None) -> DeckSpec:
    """outline: pass a (human-approved/edited) claim chain to skip stage 1.
    quality: 'best' = multi-candidate + vision judge; 'fast' = one
    candidate, no judge. progress_cb(done, total, stage) fires as work lands.

    T5.6 shape: the STORY is fixed sequentially up front — governing
    thought, claim chain, flow critic all precede any slide. Slides then
    generate in PARALLEL waves, each fenced by every other slide's claim;
    variety is assigned globally by the batch brief pre-pass and enforced
    afterwards by two deterministic sweeps (adjacent silhouettes, repeated
    headlines)."""
    log.info("spec generation via %s (%s), quality=%s",
             provider(), model_id(), quality)
    facts = FactTable.from_csv(csv_text) if csv_text else None

    def _tick(done: int, total: int, stage: str) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(done, total, stage)
        except Exception:  # noqa: BLE001 — progress must never kill a job
            pass

    _tick(0, 0, "outline")
    if outline is None:
        outline = generate_outline(prompt, facts)
    log.info("outline: %s", [o.slide_type for o in outline.slides])
    deck_context = (f"{prompt}\n\nDeck governing thought: "
                    f"{outline.governing_thought}")
    if design_directive:
        # every brief and emission reads deck_context, so the variant's
        # design personality reaches every slide with zero extra plumbing
        deck_context += ("\n\nTHIS DECK'S DESIGN LANGUAGE — every slide "
                         f"leans this way: {design_directive}")
    # designer mode: body slides are DESIGNED freeform on the canvas; the
    # outline's slide_type survives as the reliability fallback. Covers,
    # dividers and the closing exec_summary keep their dedicated molds.
    designer_on = os.environ.get("DECKENGINE_DESIGNER", "1") != "0"
    _not_designed = ("title", "section_divider", "exec_summary")
    from .designer import silhouette
    items = []
    for item in outline.slides:
        if item.slide_type not in _ARCHETYPES:
            log.warning("skipping unknown archetype %r", item.slide_type)
            continue
        items.append(item)
    if not items:
        raise RuntimeError("model produced no usable slides")
    total = len(items)
    fast = quality == "fast"
    n_cands = 1 if fast else None
    budget = JudgeBudget(0 if fast else judge_budget_default())
    # the claim-chain fence: every slide sees every OTHER slide's claim
    claims = [f"[{it.slide_type}] {it.claim}" for it in items]

    # batch design-brief pre-pass: ONE fast call assigns every designed
    # slide a distinct concept — variety decided globally before any slide
    canvas_idx = [i for i, it in enumerate(items)
                  if designer_on and it.slide_type not in _not_designed]
    briefs: dict[int, object] = {}
    if canvas_idx:
        got = _batch_briefs([(items[i].claim, items[i].visual_concept,
                              items[i].section) for i in canvas_idx], facts)
        if got:
            briefs = dict(zip(canvas_idx, got))

    lock = threading.Lock()
    sils: dict[int, str] = {}

    def _recent(i: int) -> list[str]:
        with lock:
            return [sils[k] for k in sorted(sils) if k != i][-6:]

    def _gen_one(i: int) -> BaseModel | None:
        item = items[i]
        others = claims[:i] + claims[i + 1:]
        use_canvas = designer_on and item.slide_type not in _not_designed
        try:
            if use_canvas:
                try:
                    slide = generate_slide_best(
                        "canvas", item.claim, deck_context, facts,
                        prior_slides=others, theme=theme,
                        visual_concept=item.visual_concept,
                        recent_silhouettes=_recent(i),
                        brief=briefs.get(i, "auto"),
                        n_candidates=n_cands, judge_budget=budget)
                except RuntimeError as e:
                    log.warning("canvas design failed for %r (%s); "
                                "archetype fallback %s",
                                item.claim[:50], e, item.slide_type)
                    slide = generate_slide_best(
                        item.slide_type, item.claim, deck_context, facts,
                        prior_slides=others, theme=theme,
                        n_candidates=n_cands, judge_budget=budget)
            else:
                slide = generate_slide_best(
                    item.slide_type, item.claim, deck_context, facts,
                    prior_slides=others, theme=theme,
                    n_candidates=n_cands, judge_budget=budget)
        except RuntimeError as e:
            # one stubborn slide must NEVER kill a whole deck: ship without
            # it and record the gap (the claim chain stays reviewable)
            log.warning("skipping slide %r (%s): %s",
                        item.claim[:60], item.slide_type, e)
            return None
        with lock:
            sils[i] = silhouette(slide)
        return slide

    # parallel waves: slide ORDER and the argument live in the outline, so
    # generation order is free to be concurrent — results reassemble by index
    results: dict[int, BaseModel] = {}
    done = 0
    _tick(0, total, "designing")
    workers = min(_wave_size(), total)
    if workers == 1:
        for i in range(total):
            slide = _gen_one(i)
            if slide is not None:
                results[i] = slide
            done += 1
            _tick(done, total, "designing")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_gen_one, i): i for i in range(total)}
            for fut in as_completed(futs):
                slide = fut.result()
                if slide is not None:
                    results[futs[fut]] = slide
                done += 1
                _tick(done, total, "designing")
    if not results:
        raise RuntimeError("model produced no usable slides")

    # deterministic post-sweeps: the quality gates sequential order gave,
    # now explicit. Each offender gets ONE targeted regen, bounded.
    _tick(done, total, "polishing")
    regens = 0
    order = sorted(results)
    # (i) adjacent identical silhouettes -> redesign the later slide
    for a, b in zip(order, order[1:]):
        if regens >= _MAX_SWEEP_REGENS:
            break
        if sils.get(a) and sils.get(a) == sils.get(b) \
                and getattr(results[b], "slide_type", "") == "canvas":
            item = items[b]
            log.info("silhouette sweep: redesigning slide %d", b + 1)
            try:
                redo = generate_slide_best(
                    "canvas", item.claim, deck_context, facts,
                    prior_slides=claims[:b] + claims[b + 1:], theme=theme,
                    visual_concept=item.visual_concept,
                    recent_silhouettes=[sils[a]],
                    brief=briefs.get(b, "auto"),
                    n_candidates=n_cands, judge_budget=budget)
            except RuntimeError as e:
                log.warning("silhouette sweep regen failed: %s", e)
                continue
            regens += 1
            if silhouette(redo) != sils[a]:   # keep only a real improvement
                results[b] = redo
                sils[b] = silhouette(redo)
    # (ii) two slides arguing with the same headline -> rewrite the later
    titles = [str(getattr(results[i], "title", "") or "") for i in order]
    for a, b in _dupe_pairs(titles):
        if regens >= _MAX_SWEEP_REGENS:
            break
        ia, ib = order[a], order[b]
        item = items[ib]
        log.info("content sweep: slide %d repeats slide %d — regenerating",
                 ib + 1, ia + 1)
        note = (f"[REPEAT DEFECT] slide {ia + 1} already argues "
                f"{titles[a]!r} — prove ONLY your claim with DIFFERENT "
                f"evidence and a different headline figure")
        archetype = getattr(results[ib], "slide_type", item.slide_type)
        try:
            redo = generate_slide_best(
                archetype, item.claim, deck_context, facts,
                prior_slides=[note] + claims[:ib] + claims[ib + 1:],
                theme=theme, visual_concept=item.visual_concept,
                recent_silhouettes=_recent(ib),
                brief=briefs.get(ib, "auto"),
                n_candidates=n_cands, judge_budget=budget)
        except RuntimeError as e:
            log.warning("content sweep regen failed: %s", e)
            continue
        regens += 1
        results[ib] = redo
        sils[ib] = silhouette(redo)

    # sequential tail: markers, kickers, appendix — deterministic, cheap
    slides = []
    for i in order:
        slide = results[i]
        item = items[i]
        if facts:
            # CSV facts are official by construction — mark their displays
            slide = inject_fact_markers(slide, facts)
        # section tag -> kicker, copied deterministically from the outline
        # (constant within a section; slides never invent their own)
        if item.section and hasattr(slide, "kicker"):
            slide.kicker = item.section.strip()[:40] or None
        slides.append(slide)
    if facts:
        appendix = sources_appendix(facts, slides)
        if appendix is not None:
            slides.append(appendix)
    else:
        # marker mode: legend once + the auto methodology slide
        append_legend_once(slides)
        appendix = methodology_appendix(slides)
        if appendix is not None:
            slides.append(appendix)
        cov = [marker_coverage(s) for s in slides]
        marked, total = sum(c[0] for c in cov), sum(c[1] for c in cov)
        if total:
            log.info("marker coverage: %d/%d prose figures marked",
                     marked, total)
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

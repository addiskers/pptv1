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
import shutil
import tempfile
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ValidationError

from ..schema.slide_types import DeckMeta, DeckSpec, SlideSpec
from .facts import FactTable, verify_spec_numbers
from .format_rules import (check_outline_formats, check_slide_format,
                           decision_table_text)
from .story import REVIEW_PROMPT, Outline, check_outline
from .writing import check_slide_writing

log = logging.getLogger("deckengine")

MAX_REPAIRS = 2
DEFAULTS = {"openai": "gpt-5.4", "anthropic": "claude-sonnet-5"}

_ARCHETYPES: dict[str, type[BaseModel]] = {
    m.model_fields["slide_type"].default: m for m in get_args(get_args(SlideSpec)[0])
}

SYSTEM = """You write slide specs for DeckEngine, a consulting-grade deck engine.
Hard rules:
- Titles are full-sentence takeaways ("X raised incomes 5% above state average"), never labels ("Results"). Keep titles under 160 characters. A title carries a verb and, when the facts allow, a number.
- Prefer stats, tables and comparisons over prose (assertion-evidence style): every body element is EVIDENCE for the title claim, not commentary about it.
- Use ONLY numbers given in the FACTS block, with their display strings verbatim. Never compute, extrapolate or invent a number. If no FACTS block is given, use round illustrative numbers and mark the footnote 'illustrative data'.
- Rich text markup: **bold** for emphasis on numbers/leads. *Italics* only for defined terms, at most twice per slide — italicising for tone is a machine tell.
- Writing craft: never hedge (may/might/could/potentially — state it or cut it). No exclamation marks. Never open a line with Additionally/Furthermore/Moreover. Vary sentence rhythm: a short punch, then longer support.
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
         "two consecutive slides of the same slide_type. Prefer standard "
         "archetypes; pick custom_layout when a claim needs a bespoke "
         "composition no standard mold fits — and ALWAYS for prioritisation "
         "2x2s, funnels, option scorecards or image-led slides: the "
         "matrix_2x2, funnel, harvey_balls and image_block components live "
         "only inside custom_layout trees. Open with a title slide; close "
         "with an exec_summary or kpi_dashboard when it fits.\n\n"
         + decision_table_text())
    outline = Outline.model_validate(_structured_call("emit_outline", schema, p))

    def _problems(o: Outline) -> list[str]:
        return check_outline(o) + check_outline_formats(o, facts)

    problems = _problems(outline)
    review = REVIEW_PROMPT
    if problems:
        review += ("\n\nDeterministic checks flagged these problems — fix "
                   "all of them:\n" + "\n".join(f"- {x}" for x in problems))
    review += "\n\nOUTLINE:\n" + outline.model_dump_json(indent=2)
    try:
        revised = Outline.model_validate(
            _structured_call("emit_outline", schema, review))
        if len(_problems(revised)) <= len(problems):
            outline = revised
    except (ValidationError, RuntimeError) as e:  # review is best-effort
        log.warning("outline review pass failed, keeping original: %s", e)
    return outline


_FEW_SHOTS_DIR = Path(__file__).parent / "few_shots"
WON_DIR = _FEW_SHOTS_DIR / "won"


def _few_shot(archetype: str) -> str:
    """Curated gold specs of this archetype, injected as exemplars —
    move density and structure more than any critique pass. An archetype may
    ship several ({name}.json, {name}_2.json, ...); the latest judge-picked
    winner from WON_DIR compounds on top (max 3 exemplars total)."""
    paths = [p for p in (_FEW_SHOTS_DIR / f"{archetype}.json",
                         _FEW_SHOTS_DIR / f"{archetype}_2.json")
             if p.is_file()]
    if WON_DIR.is_dir():
        won = sorted(WON_DIR.glob(f"{archetype}_*.json"),
                     key=lambda p: p.stat().st_mtime)
        if won:
            paths.append(won[-1])
    paths = paths[:3]
    if not paths:
        return ""
    return "".join(
        f"\n\nEXAMPLE {i} of an excellent spec of this type (match its "
        "density and structure, NOT its topic or numbers):\n"
        + p.read_text(encoding="utf-8")
        for i, p in enumerate(paths, start=1))


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
    # teach the format decision table where the chart choice is live
    table = ("\n\n" + decision_table_text()
             if archetype in ("chart_slide", "custom_layout") else "")
    base_prompt = (
        f"Deck request:\n{prompt}\n\n"
        f"{facts.prompt_block() if facts else ''}{prior}{_few_shot(archetype)}"
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
        wproblems = check_slide_writing(slide)
        if wproblems and attempt < MAX_REPAIRS:
            attempt_prompt = (base_prompt +
                              "\n\nWriting problems — fix ALL of them while "
                              "keeping the same facts and structure:\n" +
                              "\n".join(f"- {p}" for p in wproblems) +
                              "\nEmit the full JSON again.")
            continue
        if wproblems:
            log.warning("writing problems survived repairs: %s", wproblems)
        fproblems = check_slide_format(slide, facts)
        if fproblems and attempt < MAX_REPAIRS:
            attempt_prompt = (base_prompt +
                              "\n\nChart format problems — fix ALL of them "
                              "while keeping the same facts and claim:\n" +
                              "\n".join(f"- {p}" for p in fproblems) +
                              "\nEmit the full JSON again.")
            continue
        if fproblems:
            log.warning("format problems survived repairs: %s", fproblems)
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
    try:  # Windows + Office only; absence falls back to deterministic pick
        from ..render.preview import export_pngs_powerpoint
        pngs = export_pngs_powerpoint(pptx, pptx.parent / (pptx.stem + "_png"),
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


def generate_slide_best(archetype: str, claim: str, prompt: str,
                        facts: FactTable | None,
                        prior_slides: list[str] | None = None,
                        theme: str = "consulting_navy") -> BaseModel:
    """N candidates -> render all -> deterministic score -> ONE pairwise
    vision-judge call only when the metrics can't separate the finalists."""
    n = candidate_count()
    if n == 1:
        return generate_slide(archetype, claim, prompt, facts,
                              prior_slides=prior_slides)
    cands = []
    for i in range(n):
        p = prompt if i == 0 else prompt + _VARIANT_NUDGE
        try:
            cands.append(generate_slide(archetype, claim, p, facts,
                                        prior_slides=prior_slides))
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
        scored.sort(key=lambda cs: (cs[1]["defects"], -cs[1]["fill"]))
        best, runner = scored[0], scored[1]
        clear = (best[1]["defects"] < runner[1]["defects"]
                 or best[1]["fill"] - runner[1]["fill"] > 0.05)
        if clear or best[1]["pptx"] is None or runner[1]["pptx"] is None:
            return best[0]
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
        slide = generate_slide_best(item.slide_type, item.claim, deck_context,
                                    facts, prior_slides=prior, theme=theme)
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

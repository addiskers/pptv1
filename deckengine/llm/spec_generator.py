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
from .format_rules import (check_outline_chart_density,
                           check_outline_formats, check_slide_format,
                           decision_table_text)
from .canvas_rules import check_canvas_slide
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


def _structured_call(name: str, schema: dict, prompt: str,
                     max_tokens: int = 16000) -> dict:
    """One structured-output call, provider-dispatched, with transient-error
    retries (a network blip must never kill a 20-slide generation)."""
    import time as _time
    last: Exception | None = None
    for attempt in range(3):
        try:
            return _structured_call_once(name, schema, prompt, max_tokens)
        except (json.JSONDecodeError, RuntimeError):
            raise  # real model failures go to the repair loop, not a retry
        except Exception as e:  # noqa: BLE001 — connection/rate-limit class
            last = e
            log.warning("LLM call failed (attempt %d/3): %s", attempt + 1, e)
            _time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM unreachable after 3 attempts: {last}")


def _structured_call_once(name: str, schema: dict, prompt: str,
                          max_tokens: int = 16000) -> dict:
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
    from .narrative import flow_menu
    p = (f"Plan a slide deck for this request:\n\n{prompt}\n\n"
         f"Available slide_type values: {archetype_list}.\n"
         f"{facts.prompt_block() if facts else ''}\n"
         "FIRST choose the deck FLOW by the AUDIENCE'S META-QUESTION — not "
         "the topic (the same data answers different questions with "
         "different decks). Declare it in narrative_arc and shape the "
         "claim chain to complete that flow's argument, closing on its "
         "ask/resolution:\n" + flow_menu() + "\n\n"
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
        revised = Outline.model_validate(
            _structured_call("emit_outline", schema, review))
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
    "6-14 elements is the sweet spot; align edges to shared lines; leave "
    "real whitespace — one dominant element, everything else supports it.")


def generate_slide(archetype: str, intent: str, prompt: str,
                   facts: FactTable | None,
                   prior_slides: list[str] | None = None,
                   design_brief: str | None = None) -> BaseModel:
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
        else:
            # no-CSV mode: every figure must carry its provenance marker
            mproblems = check_slide_markers(slide)
            if mproblems and attempt < MAX_REPAIRS:
                attempt_prompt = (base_prompt +
                                  "\n\nProvenance problems — fix ALL of them "
                                  "while keeping the same claims and layout:\n" +
                                  "\n".join(f"- {p}" for p in mproblems) +
                                  "\nEmit the full JSON again.")
                continue
            if mproblems:
                log.warning("marker problems survived repairs: %s", mproblems)
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
        if slide.slide_type == "canvas":
            cproblems = check_canvas_slide(slide)
            if cproblems and attempt < MAX_REPAIRS:
                attempt_prompt = (base_prompt +
                                  "\n\nDesign problems — fix ALL of them "
                                  "while keeping the same message and "
                                  "overall composition:\n" +
                                  "\n".join(f"- {p}" for p in cproblems) +
                                  "\nEmit the full JSON again.")
                continue
            if cproblems:
                log.warning("canvas problems survived repairs: %s",
                            cproblems)
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
            max_tokens=2000)
        return DesignBrief.model_validate(raw)
    except Exception as e:  # noqa: BLE001
        log.warning("design brief failed (%s); designing without one", e)
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


def generate_slide_best(archetype: str, claim: str, prompt: str,
                        facts: FactTable | None,
                        prior_slides: list[str] | None = None,
                        theme: str = "consulting_navy",
                        visual_concept: str | None = None,
                        recent_silhouettes: list[str] | None = None) -> BaseModel:
    """N candidates -> render all -> deterministic score -> ONE pairwise
    vision-judge call only when the metrics can't separate the finalists.
    Canvas slides get a DESIGN BRIEF first; candidate 2 is briefed toward a
    different concept, and a candidate whose silhouette repeats the
    previous slide's loses the tie."""
    from .designer import silhouette
    recent = recent_silhouettes or []
    prev_sil = recent[-1] if recent else None
    brief = (_design_brief(claim, visual_concept, recent, facts)
             if archetype == "canvas" else None)
    n = candidate_count()
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
    # designer mode: body slides are DESIGNED freeform on the canvas; the
    # outline's slide_type survives as the reliability fallback. Covers,
    # dividers and the closing exec_summary keep their dedicated molds.
    designer_on = os.environ.get("DECKENGINE_DESIGNER", "1") != "0"
    _not_designed = ("title", "section_divider", "exec_summary")
    from .designer import silhouette
    slides = []
    prior: list[str] = []
    recent_sils: list[str] = []
    for item in outline.slides:
        if item.slide_type not in _ARCHETYPES:
            log.warning("skipping unknown archetype %r", item.slide_type)
            continue
        use_canvas = designer_on and item.slide_type not in _not_designed
        try:
            if use_canvas:
                try:
                    slide = generate_slide_best(
                        "canvas", item.claim, deck_context, facts,
                        prior_slides=prior, theme=theme,
                        visual_concept=item.visual_concept,
                        recent_silhouettes=recent_sils)
                except RuntimeError as e:
                    log.warning("canvas design failed for %r (%s); "
                                "archetype fallback %s",
                                item.claim[:50], e, item.slide_type)
                    slide = generate_slide_best(
                        item.slide_type, item.claim, deck_context, facts,
                        prior_slides=prior, theme=theme)
            else:
                slide = generate_slide_best(item.slide_type, item.claim,
                                            deck_context, facts,
                                            prior_slides=prior, theme=theme)
        except RuntimeError as e:
            # one stubborn slide must NEVER kill a whole deck: ship without
            # it and record the gap (the claim chain stays reviewable)
            log.warning("skipping slide %r (%s): %s",
                        item.claim[:60], item.slide_type, e)
            continue
        recent_sils.append(silhouette(slide))
        del recent_sils[:-6]
        if facts:
            # CSV facts are official by construction — mark their displays
            slide = inject_fact_markers(slide, facts)
        # section tag -> kicker, copied deterministically from the outline
        # (constant within a section; slides never invent their own)
        if item.section and hasattr(slide, "kicker"):
            slide.kicker = item.section.strip()[:40] or None
        slides.append(slide)
        title = getattr(slide, "title", None) or item.claim
        prior.append(f"[{item.slide_type}] {title}")
    if not slides:
        raise RuntimeError("model produced no usable slides")
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

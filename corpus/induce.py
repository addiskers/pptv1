"""Exemplar induction — the automated replica method (E5/E6).

The Gates goldens were made by hand: look at a reference slide, write the
DeckEngine spec, render, compare, iterate until it matches. This module does
the same loop automatically over the highest-scored corpus slides:

  draft  -> a vision call turns the slide PNG (+ its text) into a DeckEngine
            spec for the routed archetype (Pydantic-validated, repaired)
  render -> build_deck renders the draft; export a PNG
  judge  -> a fidelity vision call scores render-vs-original + lists gaps;
            below threshold with rounds left, repair from the gaps and retry
  gate   -> corpus/neutralize strips all client IP (deterministic leak gate)
  apply  -> approved specs join deckengine/llm/few_shots/ + eval/goldens/

Only the top candidates are induced (vision cost), one per source deck, with
archetype-coverage balancing. Cache/estimate/budget mirror classify.py so a
pilot run is cheap and resumable. Nothing is auto-applied: a human approves
from the review contact sheet first.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import time
from pathlib import Path

from pydantic import ValidationError

WORK_DEFAULT = Path(__file__).resolve().parent / "work"
FEW_SHOTS = (Path(__file__).resolve().parents[1] / "deckengine" / "llm"
             / "few_shots")
GOLDENS = Path(__file__).resolve().parents[1] / "eval" / "goldens"

PROMPT_VERSION = "induce-v1"
MIN_FIDELITY = 4          # 1-5; below this, repair
REPAIR_ROUNDS = 2
EST_USD_PER_SLIDE = 0.02  # draft + up to 2 judge/repair vision calls
RETRIES = 3
BACKOFF_BASE = 2.0

# corpus slide_role -> DeckEngine archetype (the mold we replicate into)
ROLE_TO_ARCHETYPE = {
    "title": "title", "divider": "section_divider",
    "exec_summary": "exec_summary", "chart": "chart_slide",
    "table": "data_deep_dive", "framework": "framework_slide",
    "timeline": "timeline_slide", "dashboard": "kpi_dashboard",
    "matrix": "custom_layout", "process_flow": "custom_layout",
    "text_bullets": "bullet_content", "other": "custom_layout",
}


# --- jsonl (torn-last-line tolerant, mirrors ingest._read_jsonl) -------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break  # torn trailing line from a crash mid-write
    return out


def _last_wins(rows: list[dict], key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        if r.get(key):
            out[r[key]] = r
    return out


# --- candidate selection -----------------------------------------------------

def select_candidates(work: Path, total_cap: int = 30,
                      per_deck_cap: int = 1,
                      per_archetype_cap: int = 4) -> list[dict]:
    """Highest-scored classified slides, routed to an archetype, balanced
    across archetypes and source decks."""
    index = _last_wins(_read_jsonl(work / "index.jsonl"), "slide_id")
    scores = _last_wins(_read_jsonl(work / "scores.jsonl"), "slide_id")
    classified = _last_wins(_read_jsonl(work / "classified.jsonl"), "slide_id")
    cands = []
    for sid, cl in classified.items():
        rec, sc = index.get(sid), scores.get(sid)
        if rec is None or sc is None:
            continue
        role = cl.get("slide_role", "other")
        archetype = ROLE_TO_ARCHETYPE.get(role, "custom_layout")
        cands.append({
            "slide_id": sid, "deck_id": rec.get("deck_id"),
            "png_path": rec.get("png_path"),
            "extracted_text": rec.get("extracted_text", ""),
            "archetype": archetype, "score": sc.get("score", 0),
            "anchor": cl.get("anchor", "mediocre"),
            "confidence": cl.get("confidence", 0.0)})
    # only strong slides; best first
    cands = [c for c in cands
             if c["anchor"] == "great" and c["confidence"] >= 0.6]
    cands.sort(key=lambda c: -c["score"])
    picked: list[dict] = []
    seen_decks: set[str] = set()
    per_arch: dict[str, int] = {}
    for c in cands:
        if len(picked) >= total_cap:
            break
        if per_deck_cap and c["deck_id"] in seen_decks:
            continue
        if per_arch.get(c["archetype"], 0) >= per_archetype_cap:
            continue
        picked.append(c)
        seen_decks.add(c["deck_id"])
        per_arch[c["archetype"]] = per_arch.get(c["archetype"], 0) + 1
    return picked


# --- provider IO (module attributes; monkeypatched in tests) -----------------

def _draft_call(schema: dict, png: bytes, text: str, feedback: str) -> dict:
    """Vision call: slide PNG + text -> a spec dict for the archetype."""
    from deckengine.llm.spec_generator import model_id, provider
    instr = ("Reverse-engineer this consulting slide into a DeckEngine spec "
             "that RECREATES its structure, density, layout and chart form so "
             "a render passes the squint test against the original. Match the "
             "component mix and word counts; do NOT use image components. "
             + feedback + "\nRespond ONLY with a JSON object validating "
             "against this schema:\n" + json.dumps(schema)
             + "\n\nExtracted slide text (for wording):\n" + text[:1500])
    b64 = base64.standard_b64encode(png).decode("ascii")
    if provider() == "openai":
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model_id(), max_completion_tokens=6000,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": instr},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + b64}}]}])
        return json.loads(resp.choices[0].message.content)
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model_id(), max_tokens=6000,
        tools=[{"name": "emit_spec", "description": "Emit the slide spec.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": "emit_spec"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": instr},
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png",
                                         "data": b64}}]}])
    return next(b.input for b in resp.content if b.type == "tool_use")


def _fidelity_call(original: bytes, replica: bytes) -> dict:
    """Vision call: score render-vs-original structural fidelity + gaps."""
    from deckengine.llm.spec_generator import model_id, provider
    prompt = ("Image A is a reference consulting slide; image B is a "
              "reproduction. Score B's STRUCTURAL fidelity to A from 1-5 "
              "(layout shape, hierarchy, density, chart form — ignore exact "
              "wording and colors) and list the 3 biggest structural gaps.")
    schema = {"type": "object", "properties": {
        "score": {"type": "integer"},
        "gaps": {"type": "array", "items": {"type": "string"}}},
        "required": ["score", "gaps"]}
    a = base64.standard_b64encode(original).decode("ascii")
    b = base64.standard_b64encode(replica).decode("ascii")
    if provider() == "openai":
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model_id(), max_completion_tokens=1500,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt + "\nRespond ONLY with JSON "
                 '{"score": 1-5, "gaps": [...]}.'},
                {"type": "text", "text": "Image A (reference):"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + a}},
                {"type": "text", "text": "Image B (reproduction):"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + b}}]}])
        return json.loads(resp.choices[0].message.content)
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model_id(), max_tokens=1500,
        tools=[{"name": "score", "description": "Score fidelity.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": "score"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "text", "text": "Image A (reference):"},
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png", "data": a}},
            {"type": "text", "text": "Image B (reproduction):"},
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png",
                                         "data": b}}]}])
    return next(x.input for x in resp.content if x.type == "tool_use")


def _with_backoff(fn, *args):
    delay = BACKOFF_BASE
    for attempt in range(RETRIES):
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001
            if attempt == RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


# --- the induction loop for one slide ----------------------------------------

def _archetype_schema(archetype: str) -> tuple[dict, object]:
    from deckengine.llm.spec_generator import _ARCHETYPES
    model_cls = _ARCHETYPES[archetype]
    return model_cls.model_json_schema(), model_cls


def _draft_valid(archetype: str, png: bytes, text: str,
                 feedback: str = "") -> object | None:
    schema, model_cls = _archetype_schema(archetype)
    raw = _with_backoff(_draft_call, schema, png, text, feedback)
    raw.setdefault("slide_type", archetype)
    try:
        return model_cls.model_validate(raw)
    except ValidationError:
        # one repair attempt on schema errors
        raw2 = _with_backoff(_draft_call, schema, png, text,
                             feedback + " The prior attempt failed schema "
                             "validation; emit a valid object.")
        raw2.setdefault("slide_type", archetype)
        try:
            return model_cls.model_validate(raw2)
        except ValidationError:
            return None


def _render_png(spec_model, workdir: Path, tag: str) -> Path | None:
    """Render a one-slide deck and export its PNG; None if unavailable."""
    from deckengine.render.deck_builder import build_deck
    from deckengine.schema.slide_types import DeckMeta, DeckSpec
    out = workdir / f"{tag}.pptx"
    try:
        build_deck(DeckSpec(theme="consulting_paper",
                            meta=DeckMeta(title="induced"),
                            slides=[spec_model]), out)
    except Exception:  # noqa: BLE001
        return None
    try:
        from deckengine.render.preview import export_pngs_powerpoint
        pngs = export_pngs_powerpoint(out, workdir / (tag + "_png"),
                                      width=1280, height=720)
        return pngs[0] if pngs else None
    except Exception:  # noqa: BLE001
        return None


def induce_one(cand: dict, work: Path) -> dict:
    """Run the full loop for one candidate; returns a result record."""
    from deckengine.schema.slide_types import SlideSpec  # noqa: F401
    out_dir = work / "induce" / cand["slide_id"].replace(":", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    png = Path(cand["png_path"]).read_bytes()
    text = cand["extracted_text"]
    archetype = cand["archetype"]

    feedback = ""
    best = None
    for rnd in range(REPAIR_ROUNDS + 1):
        spec = _draft_valid(archetype, png, text, feedback)
        if spec is None:
            return {"slide_id": cand["slide_id"], "ok": False,
                    "reason": "draft failed schema after repair"}
        replica = _render_png(spec, out_dir, f"r{rnd}")
        if replica is None:
            return {"slide_id": cand["slide_id"], "ok": False,
                    "reason": "render/preview unavailable"}
        verdict = _with_backoff(_fidelity_call, png, replica.read_bytes())
        score = int(verdict.get("score", 0))
        best = {"spec": spec, "score": score, "gaps": verdict.get("gaps", []),
                "replica": str(replica)}
        if score >= MIN_FIDELITY or rnd == REPAIR_ROUNDS:
            break
        feedback = ("Your previous reproduction scored " + str(score)
                    + "/5. Fix these structural gaps: "
                    + "; ".join(verdict.get("gaps", [])) + ".")

    # neutralize + leak gate
    from .neutralize import neutralize_spec
    neutral, leaked = neutralize_spec(best["spec"].model_dump(), text,
                                      archetype)
    result = {"slide_id": cand["slide_id"], "archetype": archetype,
              "fidelity": best["score"], "gaps": best["gaps"],
              "leaked": leaked, "ok": neutral is not None and best["score"]
              >= MIN_FIDELITY, "replica_png": best["replica"],
              "source_png": cand["png_path"]}
    (out_dir / "draft.json").write_text(
        json.dumps(best["spec"].model_dump(), indent=2), encoding="utf-8")
    if neutral is not None:
        (out_dir / "neutralized.json").write_text(
            json.dumps(neutral, indent=2), encoding="utf-8")
    (out_dir / "verdict.json").write_text(json.dumps(result), encoding="utf-8")
    return result


# --- run + apply -------------------------------------------------------------

def run_induce(work: Path, total_cap: int = 30, estimate: bool = False,
               budget_usd: float | None = None,
               limit: int | None = None) -> dict:
    cands = select_candidates(work, total_cap=total_cap)
    done = {r["slide_id"] for r in _read_jsonl(work / "induced.jsonl")}
    pending = [c for c in cands if c["slide_id"] not in done]
    if limit is not None:
        pending = pending[:limit]
    est = round(len(pending) * EST_USD_PER_SLIDE, 2)
    if estimate:
        return {"candidates": len(cands), "pending": len(pending),
                "est_usd": est}
    if budget_usd is not None and est > budget_usd:
        raise SystemExit(f"estimated ${est:.2f} for {len(pending)} slides "
                         f"exceeds budget ${budget_usd:.2f}; aborting")
    results = []
    for c in pending:
        try:
            r = induce_one(c, work)
        except Exception as exc:  # noqa: BLE001 — never crash the batch
            r = {"slide_id": c["slide_id"], "ok": False,
                 "reason": f"{type(exc).__name__}: {exc}"}
        with (work / "induced.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(r) + "\n")
        results.append(r)
    ok = sum(1 for r in results if r.get("ok"))
    return {"induced": len(results), "passed": ok,
            "failed": len(results) - ok}


def apply_approved(work: Path, approved_ids: list[str],
                   few_shots: Path = FEW_SHOTS,
                   goldens: Path = GOLDENS) -> dict:
    """Copy approved neutralized specs into the few-shot + golden libraries.
    Golden gets a full one-slide DeckSpec; few-shot gets the slide spec."""
    applied = 0
    for sid in approved_ids:
        d = work / "induce" / sid.replace(":", "_")
        neu = d / "neutralized.json"
        if not neu.is_file():
            continue
        spec = json.loads(neu.read_text(encoding="utf-8"))
        archetype = spec.get("slide_type", "custom_layout")
        stem = f"corpus_{sid.replace(':', '_')}"
        # few-shot: next free {archetype}_N.json slot the loader will pick up
        n = 2
        while (few_shots / f"{archetype}_{n}.json").is_file():
            n += 1
        (few_shots / f"{archetype}_{n}.json").write_text(
            json.dumps(spec, indent=2), encoding="utf-8")
        # golden: wrap as a renderable deck for the eval harness
        deck = {"schema_version": 1, "theme": "consulting_paper",
                "meta": {"title": stem}, "slides": [spec]}
        (goldens / f"{stem}.json").write_text(
            json.dumps(deck, indent=2), encoding="utf-8")
        applied += 1
    return {"applied": applied}


def main(argv: list[str] | None = None) -> None:
    from deckengine.envfile import load_env
    load_env()
    ap = argparse.ArgumentParser(description="Induce exemplar specs from the "
                                 "highest-scored corpus slides.")
    ap.add_argument("--work", default=str(WORK_DEFAULT))
    ap.add_argument("--cap", type=int, default=30)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--budget-usd", type=float, default=None)
    ap.add_argument("--apply", default=None,
                    help="path to a file of approved slide_ids (one/line)")
    args = ap.parse_args(argv)
    work = Path(args.work)
    if args.apply:
        ids = [ln.strip() for ln in Path(args.apply).read_text(
            encoding="utf-8").splitlines() if ln.strip()]
        print(json.dumps(apply_approved(work, ids)))
        return
    print(json.dumps(run_induce(work, total_cap=args.cap,
                                estimate=args.estimate,
                                budget_usd=args.budget_usd,
                                limit=args.limit)))


if __name__ == "__main__":
    main()

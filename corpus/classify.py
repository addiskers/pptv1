"""Vision classification of surviving corpus slides (one call each).

CLI:  python corpus/classify.py [--work DIR] [--sample F] [--limit N]
                                [--estimate] [--budget-usd X]
                                [--anchors DIR]

Reads work/index.jsonl + work/filtered.jsonl (keep=true, canonical
slides only — dup_of skipped), sends each slide PNG (downscaled to a
1024px long edge) through ONE provider vision call and appends the
validated SlideClassification to work/classified.jsonl — the taxonomy
consumed by style-prior mining and the human contact sheet.

Design: pure helpers (downscale, cache key, sampling, JSONL IO with the
torn-last-line tolerance pattern from corpus/ingest.py) are separated
from provider IO; _vision_call is a module attribute so tests can
monkeypatch it (never network). Provider dispatch mirrors
deckengine/llm/judge.py (OpenAI json_object / Anthropic forced tool).
Three anchor images (great/mediocre/bad.png) calibrate the anchor
grade; a missing anchors dir degrades to model judgment with a warning.
Responses cache under work/cache/classify keyed on
sha256(png bytes + PROMPT_VERSION + model id); resume skips slide_ids
already in classified.jsonl; --estimate reports pending count and cost
without calling; --budget-usd aborts (SystemExit) before the first call
when the estimate exceeds the budget. A 4-thread pool with exponential
backoff runs the calls; per-slide failures land in
work/classify_errors.jsonl and never crash the run.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field, ValidationError, field_validator

if __package__ in (None, ""):  # allow `python corpus/classify.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

log = logging.getLogger("deckengine")

PROMPT_VERSION = "classify-v1"
MAX_LONG_EDGE = 1024
TEXT_SNIPPET = 500
MAX_REPAIRS = 2
POOL_WORKERS = 4
RETRIES = 3
BACKOFF_BASE = 1.0
# Rough all-in price of one vision classification call (anchor + slide
# images, schema, output). Used only for --estimate / --budget-usd.
COST_PER_CALL_USD = 0.015

CRAFT_VOCAB = frozenset({
    "brace", "arrow_callout", "icon_rail", "harvey_balls", "chevron",
    "timeline_bar", "kpi_cards", "heatmap_cells", "watermark_image",
    "photo_background", "big_number", "framework_2x2", "funnel",
    "legend_chips", "numbered_steps", "so_what_band",
})

ANCHOR_FILES = (("great", "great.png"), ("mediocre", "mediocre.png"),
                ("bad", "bad.png"))


# --- boundary records --------------------------------------------------------

class ChartFeatures(BaseModel):
    chart_type: Literal["bar", "stacked_bar", "grouped_bar", "line",
                        "area", "donut_pie", "waterfall", "scatter",
                        "bubble", "combo", "mekko", "other"]
    n_series: int = Field(ge=0)
    n_categories: int = Field(ge=0)
    value_labels: bool
    endpoint_labels: bool
    avg_or_target_line: bool
    delta_brackets: bool
    cagr_arrow: bool
    forecast_dashed: bool
    indexed_base100: bool
    area_fill: bool
    series_highlight: bool
    sorted_desc: bool
    annotations: int = Field(ge=0)
    legend_position: Literal["top", "right", "bottom", "inline", "none"]


class LayoutPattern(BaseModel):
    structure: Literal["single", "two_col", "three_col", "four_plus_col",
                       "rows_stack", "sidebar_left", "sidebar_right",
                       "grid", "header_band_plus_body", "full_bleed"]
    has_kicker: bool
    has_bottom_band: bool
    has_source_footer: bool


class SlideClassification(BaseModel):
    slide_id: str
    slide_role: Literal["title", "divider", "exec_summary", "chart",
                        "table", "framework", "timeline", "dashboard",
                        "matrix", "process_flow", "text_bullets", "other"]
    claim_context: Literal["growth", "share_mix", "ranking_comparison",
                           "trend_forecast", "process_roadmap",
                           "segmentation", "benchmark",
                           "economics_waterfall", "org_capability",
                           "other"]
    chart: ChartFeatures | None = None
    layout: LayoutPattern
    density: int = Field(ge=1, le=5)
    text_amount: Literal["minimal", "light", "moderate", "heavy"]
    craft_elements: list[str] = Field(default_factory=list)
    title_is_action: bool
    anchor: Literal["great", "mediocre", "bad"]
    firm_style: Literal["mck_like", "bcg_like", "bain_like", "other",
                        "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("craft_elements")
    @classmethod
    def _craft_in_vocab(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in CRAFT_VOCAB]
        if bad:
            raise ValueError(
                f"unknown craft tags {bad}; allowed: "
                f"{sorted(CRAFT_VOCAB)}")
        seen: set[str] = set()
        out: list[str] = []
        for t in v:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out


# --- jsonl IO (torn-last-line tolerant, as in corpus/ingest.py) --------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # Torn line from a crash mid-append: skipping just re-does
            # (or re-shows) one slide; raising would brick every run.
            continue
    return rows


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# --- pure helpers ------------------------------------------------------------

def downscale_png(data: bytes, max_edge: int = MAX_LONG_EDGE) -> bytes:
    """PNG bytes resized so the long edge is <= max_edge (aspect kept);
    returns the input untouched when already small enough."""
    with Image.open(io.BytesIO(data)) as img:
        w, h = img.size
        if max(w, h) <= max_edge:
            return data
        scale = max_edge / max(w, h)
        resized = img.resize((max(1, round(w * scale)),
                              max(1, round(h * scale))),
                             Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    resized.save(buf, "PNG")
    return buf.getvalue()


def _cache_key(png: bytes, model: str) -> str:
    h = hashlib.sha256()
    h.update(png)
    h.update(PROMPT_VERSION.encode("utf-8"))
    h.update(model.encode("utf-8"))
    return h.hexdigest()


def _cache_model_id() -> str:
    # Cache keys must be computable without API keys (tests, --estimate
    # on a keyless box); fall back to a fixed sentinel.
    try:
        from deckengine.llm.spec_generator import model_id
        return model_id()
    except Exception:
        return "unknown-model"


def _sampled(slide_id: str, frac: float) -> bool:
    """Deterministic per-slide sampling so --sample is resume-stable."""
    h = hashlib.sha256(("sample:" + slide_id).encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF < frac


def _call_schema() -> dict:
    """SlideClassification JSON schema minus slide_id (injected by us)."""
    schema = SlideClassification.model_json_schema()
    schema.get("properties", {}).pop("slide_id", None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"]
                              if r != "slide_id"]
    return schema


# --- prompt assembly ---------------------------------------------------------

INSTRUCTIONS = """Classify this consulting slide. Judge ONLY what you see.
- slide_role: the slide's job in the deck.
- claim_context: the kind of argument the slide's evidence makes.
- chart: fill ONLY when a data chart is the dominant element, else null.
- layout: the macro structure of the body region.
- density 1-5: 1 = sparse/empty, 5 = wall-to-wall consulting density.
- craft_elements: ONLY tags from the allowed vocabulary, only when
  clearly visible.
- title_is_action: true when the title is a full-sentence takeaway with
  a verb, not a label.
- anchor: overall craft grade calibrated against the anchor images. If
  no anchors were provided, grade against top-tier consulting output.
- firm_style: visual house style when recognizable, else unknown.
Respond with a single JSON object shaped EXACTLY like the schema — no
prose, no markdown fences."""

ANCHOR_INTRO = ("CALIBRATION ANCHORS — three reference slides graded "
                "great, mediocre and bad. Grade the target slide's "
                "`anchor` field against these.")

Part = tuple[str, object]  # ("text", str) | ("image", png bytes)


def _load_anchor_parts(anchors: str | Path | None) -> list[Part]:
    d = Path(anchors) if anchors else (
        Path(__file__).resolve().parent / "anchors")
    paths = {label: d / fname for label, fname in ANCHOR_FILES}
    if not all(p.is_file() for p in paths.values()):
        log.warning(
            "anchors dir %s missing great/mediocre/bad.png; classifying "
            "WITHOUT anchor exemplars (anchor set by model judgment)", d)
        return []
    parts: list[Part] = [("text", ANCHOR_INTRO)]
    for label, fname in ANCHOR_FILES:
        parts.append(("text", f"Anchor '{label}':"))
        parts.append(("image", downscale_png(paths[label].read_bytes())))
    return parts


def _slide_parts(rec: dict, png: bytes) -> list[Part]:
    text = (rec.get("extracted_text") or "")[:TEXT_SNIPPET]
    return [
        ("text", "SLIDE EXTRACTED TEXT (first "
         f"{TEXT_SNIPPET} chars):\n{text}"),
        ("text", "SLIDE IMAGE (the slide to classify):"),
        ("image", downscale_png(png)),
        ("text", INSTRUCTIONS + "\nAllowed craft_elements tags: "
         + ", ".join(sorted(CRAFT_VOCAB)) + "."),
    ]


# --- provider IO (dispatch mirrors deckengine/llm/judge.py) -------------------

def _vision_call(schema: dict, parts: list[Part]) -> dict:
    """ONE vision call returning the raw JSON dict. Module attribute so
    tests monkeypatch it; raises on provider errors."""
    from deckengine.llm.spec_generator import model_id, provider
    if provider() == "openai":
        from openai import OpenAI
        client = OpenAI()
        content: list[dict] = [{"type": "text", "text":
                                "Respond ONLY with a single JSON object "
                                "(no prose, no markdown fences) that "
                                "validates against this JSON Schema:\n"
                                + json.dumps(schema)}]
        for kind, val in parts:
            if kind == "text":
                content.append({"type": "text", "text": val})
            else:
                b64 = base64.standard_b64encode(val).decode("ascii")
                content.append({"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + b64}})
        resp = client.chat.completions.create(
            model=model_id(), max_completion_tokens=4000,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}])
        return json.loads(resp.choices[0].message.content)

    import anthropic
    client = anthropic.Anthropic()
    content = []
    for kind, val in parts:
        if kind == "text":
            content.append({"type": "text", "text": val})
        else:
            b64 = base64.standard_b64encode(val).decode("ascii")
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": b64}})
    resp = client.messages.create(
        model=model_id(), max_tokens=4000,
        tools=[{"name": "classify_slide",
                "description": "Emit the slide classification.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": "classify_slide"},
        messages=[{"role": "user", "content": content}])
    return next(b.input for b in resp.content if b.type == "tool_use")


def _call_with_backoff(schema: dict, parts: list[Part]) -> dict:
    delay = BACKOFF_BASE
    for attempt in range(RETRIES):
        try:
            return _vision_call(schema, parts)
        except Exception as exc:
            if attempt == RETRIES - 1:
                raise
            log.warning("vision call failed (%s); retrying in %.1fs",
                        exc, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


# --- per-slide classification -------------------------------------------------

def classify_one(rec: dict, anchor_parts: list[Part], cache_dir: Path,
                 model: str) -> tuple[SlideClassification, bool]:
    """Classify one slide; returns (classification, served_from_cache).
    Validation failures trigger a repair call with the errors attached."""
    png = Path(rec["png_path"]).read_bytes()
    cache_file = cache_dir / (_cache_key(png, model) + ".json")
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["slide_id"] = rec["slide_id"]
            return SlideClassification.model_validate(data), True
        except (json.JSONDecodeError, ValidationError):
            pass  # stale/torn cache entry: fall through to a fresh call
    parts = list(anchor_parts) + _slide_parts(rec, png)
    schema = _call_schema()
    raw = _call_with_backoff(schema, parts)
    for attempt in range(MAX_REPAIRS + 1):
        candidate = dict(raw) if isinstance(raw, dict) else raw
        if isinstance(candidate, dict):
            candidate["slide_id"] = rec["slide_id"]
        try:
            cls = SlideClassification.model_validate(candidate)
            break
        except ValidationError as exc:
            if attempt == MAX_REPAIRS:
                raise
            raw = _call_with_backoff(schema, parts + [(
                "text",
                "Your previous JSON failed validation:\n"
                f"{exc}\nEmit ONLY a corrected JSON object.")])
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(cls.model_dump_json(), encoding="utf-8")
    return cls, False


# --- run ----------------------------------------------------------------------

def run_classify(work: str | Path, sample: float | None = None,
                 limit: int | None = None, estimate: bool = False,
                 budget_usd: float | None = None,
                 anchors: str | Path | None = None) -> dict:
    """Classify pending surviving slides. Raises SystemExit before any
    provider call when the cost estimate exceeds budget_usd."""
    work = Path(work).resolve()
    index = {r.get("slide_id"): r
             for r in _read_jsonl(work / "index.jsonl")}
    keep: dict[str, bool] = {}  # last verdict per slide_id wins,
    for v in _read_jsonl(work / "filtered.jsonl"):  # as in score.py
        sid = v.get("slide_id")
        if sid:
            keep[sid] = bool(v.get("keep"))
    keep_ids = [s for s, k in keep.items() if k]
    surviving = [index[s] for s in keep_ids
                 if s in index and not index[s].get("dup_of")]
    done = {r.get("slide_id")
            for r in _read_jsonl(work / "classified.jsonl")}
    pending = [r for r in surviving if r["slide_id"] not in done]
    if sample is not None:
        pending = [r for r in pending if _sampled(r["slide_id"], sample)]
    if limit is not None:
        pending = pending[:limit]

    model = _cache_model_id()
    cache_dir = work / "cache" / "classify"
    uncached = 0
    for r in pending:
        try:
            key = _cache_key(Path(r["png_path"]).read_bytes(), model)
            if not (cache_dir / (key + ".json")).exists():
                uncached += 1
        except OSError:
            uncached += 1  # unreadable png -> counted, errors later
    est = round(uncached * COST_PER_CALL_USD, 4)
    if estimate:
        return {"pending": len(pending), "uncached": uncached,
                "est_usd": est}
    if budget_usd is not None and est > budget_usd:
        raise SystemExit(
            f"estimated ${est:.4f} for {uncached} calls exceeds budget "
            f"${budget_usd:.4f}; aborting before any call")

    anchor_parts = _load_anchor_parts(anchors)
    classified = cached = errors = 0
    with ThreadPoolExecutor(max_workers=POOL_WORKERS) as pool:
        futs = [(pool.submit(classify_one, r, anchor_parts, cache_dir,
                             model), r) for r in pending]
        # Consume in submission order (not as_completed): calls still
        # run 4-wide, but classified.jsonl / classify_errors.jsonl line
        # order is deterministic — same inputs, byte-identical outputs.
        for fut, rec in futs:
            try:
                cls, was_cached = fut.result()
            except Exception as exc:  # one bad slide never kills the run
                errors += 1
                _append_jsonl(work / "classify_errors.jsonl", [{
                    "slide_id": rec.get("slide_id"),
                    "error": f"{type(exc).__name__}: {exc}"}])
                continue
            _append_jsonl(work / "classified.jsonl", [cls.model_dump()])
            classified += 1
            cached += int(was_cached)
    return {"classified": classified, "cached": cached, "errors": errors,
            "skipped_done": len(done & {r["slide_id"]
                                        for r in surviving}),
            "pending": len(pending), "est_usd": est}


def main(argv: list[str] | None = None) -> None:
    # provider keys live in the repo .env (same pattern as api/main.py)
    from deckengine.envfile import load_env
    load_env()
    ap = argparse.ArgumentParser(
        description="Vision-classify surviving corpus slides.")
    ap.add_argument("--work",
                    default=str(Path(__file__).resolve().parent / "work"),
                    help="derived-data dir (default: corpus/work)")
    ap.add_argument("--sample", type=float, default=None,
                    help="classify only this deterministic fraction")
    ap.add_argument("--limit", type=int, default=None,
                    help="max slides this run")
    ap.add_argument("--estimate", action="store_true",
                    help="print pending count + cost estimate and exit")
    ap.add_argument("--budget-usd", type=float, default=None,
                    help="abort if the cost estimate exceeds this")
    ap.add_argument("--anchors", default=None,
                    help="dir with great/mediocre/bad.png "
                         "(default: corpus/anchors)")
    args = ap.parse_args(argv)
    summary = run_classify(args.work, sample=args.sample,
                           limit=args.limit, estimate=args.estimate,
                           budget_usd=args.budget_usd,
                           anchors=args.anchors)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()

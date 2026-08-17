"""Form census — classify cluster-representative corpus slides against THE
CANON's vocabulary (deckengine/llm/canon.py), producing the ranked evidence
for which visual forms top firms actually use.

CLI:  python corpus/census.py [--work DIR] [--sample N] [--estimate]
                              [--budget-usd X]

Selection: for each layout cluster (work/clusters.jsonl) take its
highest-craft-score member (work/scores.jsonl), cap 6 per source deck so
no single deck dominates, rank by score, keep the top --sample (350).
One cheap vision call per slide (cached under work/cache/census, resume
via work/census.jsonl) classifies primary/secondary form + flow role.
Outputs: work/census.jsonl (per slide), work/form_census.json (ranked
aggregate w/ exemplar paths), work/census_sheets/<form>.png contact
sheets for eyeballing.

Reuses corpus/classify.py's provider IO, backoff, downscale and JSONL
helpers; unknown forms coerce to "other" (validators, never repairs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

if __package__ in (None, ""):  # allow `python corpus/census.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import classify as cz  # noqa: E402
from deckengine.llm.canon import CANON, census_vocabulary  # noqa: E402

log = logging.getLogger("deckengine")

PROMPT_VERSION = "census-v1"
COST_PER_CALL_USD = 0.012
PER_DECK_CAP = 6
FLOW_ROLES = ("opener", "context", "evidence", "comparison", "options",
              "recommendation", "roadmap", "appendix", "divider", "other")


def _coerce_form(v):
    v = (v or "other").strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in set(census_vocabulary()) else "other"


class CensusRecord(BaseModel):
    slide_id: str
    primary_form: str
    secondary_form: str | None = None
    flow_role: Literal[FLOW_ROLES] = "other"  # type: ignore[valid-type]
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("primary_form", "secondary_form", mode="before")
    @classmethod
    def _form_in_vocab(cls, v):
        if v is None:
            return None
        return _coerce_form(str(v))

    @field_validator("flow_role", mode="before")
    @classmethod
    def _role_known(cls, v):
        v = (str(v or "other")).strip().lower()
        return v if v in FLOW_ROLES else "other"


def _prompt() -> str:
    fams: dict[str, list[str]] = defaultdict(list)
    for f in CANON.values():
        fams[f.family].append(f.id)
    vocab_lines = [f"- {fam}: {', '.join(ids)}"
                   for fam, ids in fams.items()]
    return (
        "Classify this consulting slide's DOMINANT visual form.\n"
        "primary_form: the ONE form that carries the slide, from this "
        "vocabulary (plus photo_hero, text_only, other):\n"
        + "\n".join(vocab_lines) +
        "\nsecondary_form: a clearly-present second form, else null.\n"
        "flow_role: the slide's job in the deck's story — one of: "
        + ", ".join(FLOW_ROLES) + ".\n"
        "confidence: 0-1. Respond ONLY with the JSON object.")


def _cache_key(png: bytes) -> str:
    h = hashlib.sha256()
    h.update(png)
    h.update(PROMPT_VERSION.encode())
    h.update(cz._cache_model_id().encode())
    return h.hexdigest()


def pick_representatives(work: Path, sample: int) -> list[dict]:
    """Best-scored member per cluster, per-deck capped, top-N by score."""
    scores = {r["slide_id"]: r.get("score", 0)
              for r in cz._read_jsonl(work / "scores.jsonl")}
    index = {r["slide_id"]: r for r in cz._read_jsonl(work / "index.jsonl")}
    reps: list[tuple[float, dict]] = []
    for cluster in cz._read_jsonl(work / "clusters.jsonl"):
        members = [s for s in cluster.get("slide_ids", []) if s in index]
        if not members:
            continue
        best = max(members, key=lambda s: scores.get(s, 0))
        rec = index[best]
        if Path(rec.get("png_path", "")).is_file():
            reps.append((scores.get(best, 0), rec))
    reps.sort(key=lambda t: -t[0])
    out, per_deck = [], Counter()
    for score, rec in reps:
        deck = rec["slide_id"].split(":")[0]
        if per_deck[deck] >= PER_DECK_CAP:
            continue
        per_deck[deck] += 1
        out.append(rec)
        if len(out) >= sample:
            break
    return out


def census_one(rec: dict, cache_dir: Path) -> tuple[CensusRecord, bool]:
    png = Path(rec["png_path"]).read_bytes()
    cache_file = cache_dir / (_cache_key(png) + ".json")
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["slide_id"] = rec["slide_id"]
            return CensusRecord.model_validate(data), True
        except Exception:  # noqa: BLE001 — torn cache falls through
            pass
    schema = CensusRecord.model_json_schema()
    schema.get("properties", {}).pop("slide_id", None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"]
                              if r != "slide_id"]
    parts = [("text", "SLIDE IMAGE:"),
             ("image", cz.downscale_png(png)),
             ("text", _prompt())]
    raw = cz._call_with_backoff(schema, parts)
    if isinstance(raw, dict):
        raw["slide_id"] = rec["slide_id"]
    out = CensusRecord.model_validate(raw)  # validators coerce, never fail
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(out.model_dump_json(), encoding="utf-8")
    return out, False


def aggregate(work: Path) -> dict:
    rows = cz._read_jsonl(work / "census.jsonl")
    scores = {r["slide_id"]: r.get("score", 0)
              for r in cz._read_jsonl(work / "scores.jsonl")}
    index = {r["slide_id"]: r for r in cz._read_jsonl(work / "index.jsonl")}
    by_form: dict[str, list[dict]] = defaultdict(list)
    roles = Counter()
    for r in rows:
        by_form[r["primary_form"]].append(r)
        if r.get("secondary_form"):
            by_form[r["secondary_form"]].append({**r, "_secondary": True})
        roles[r.get("flow_role", "other")] += 1
    total = max(1, len(rows))
    census = {}
    for form, members in sorted(by_form.items(),
                                key=lambda kv: -len(kv[1])):
        prim = [m for m in members if not m.get("_secondary")]
        ex = sorted(prim, key=lambda m: -scores.get(m["slide_id"], 0))[:6]
        census[form] = {
            "count": len(prim),
            "share": round(len(prim) / total, 3),
            "with_secondary": len(members) - len(prim),
            "status": (CANON[form].status if form in CANON else "n/a"),
            "exemplars": [
                {"slide_id": m["slide_id"],
                 "png": index.get(m["slide_id"], {}).get("png_path"),
                 "score": scores.get(m["slide_id"], 0)} for m in ex],
        }
    out = {"n_classified": len(rows), "forms": census,
           "flow_roles": dict(roles)}
    (work / "form_census.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    return out


def contact_sheets(work: Path, top: int = 12) -> None:
    from PIL import Image
    data = json.loads((work / "form_census.json").read_text(encoding="utf-8"))
    sheets = work / "census_sheets"
    sheets.mkdir(exist_ok=True)
    for form, info in list(data["forms"].items())[:top]:
        pngs = [e["png"] for e in info["exemplars"] if e.get("png")
                and Path(e["png"]).is_file()][:6]
        if not pngs:
            continue
        thumbs = []
        for p in pngs:
            with Image.open(p) as im:
                im.thumbnail((640, 360))
                thumbs.append(im.copy())
        cols = min(3, len(thumbs))
        rows_n = (len(thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 650, rows_n * 380), "white")
        for i, t in enumerate(thumbs):
            sheet.paste(t, ((i % cols) * 650 + 5, (i // cols) * 380 + 10))
        sheet.save(sheets / f"{form}.png")


def main() -> int:
    from deckengine.envfile import load_env
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path(__file__).parent / "work"))
    ap.add_argument("--sample", type=int, default=350)
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--budget-usd", type=float, default=5.0)
    args = ap.parse_args()
    work = Path(args.work)

    reps = pick_representatives(work, args.sample)
    done = {r["slide_id"] for r in cz._read_jsonl(work / "census.jsonl")}
    pending = [r for r in reps if r["slide_id"] not in done]
    est = len(pending) * COST_PER_CALL_USD
    print(f"representatives: {len(reps)}  pending: {len(pending)}  "
          f"est ${est:.2f}")
    if args.estimate:
        return 0
    if est > args.budget_usd:
        print(f"ABORT: estimate ${est:.2f} exceeds budget "
              f"${args.budget_usd:.2f} — lower --sample")
        return 1

    cache_dir = work / "cache" / "census"
    hits = 0

    def run(rec):
        try:
            out, cached = census_one(rec, cache_dir)
            return out, cached, None
        except Exception as exc:  # noqa: BLE001
            return None, False, f"{rec['slide_id']}: {exc}"

    with ThreadPoolExecutor(max_workers=cz.POOL_WORKERS) as pool:
        for out, cached, err in pool.map(run, pending):
            if err:
                cz._append_jsonl(work / "census_errors.jsonl",
                                 [{"error": err}])
                continue
            hits += 1 if cached else 0
            cz._append_jsonl(work / "census.jsonl", [out.model_dump()])

    data = aggregate(work)
    contact_sheets(work)
    print(f"classified {data['n_classified']} slides ({hits} cache hits)")
    print(f"{'form':<22}{'count':>6}{'share':>8}  status")
    for form, info in list(data["forms"].items())[:20]:
        print(f"{form:<22}{info['count']:>6}{info['share']:>8.1%}  "
              f"{info['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

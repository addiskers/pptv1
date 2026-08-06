"""Human contact sheet over the classified corpus.

CLI:  python corpus/review.py [--work DIR] [--out FILE]
                              [--apply APPROVED_TXT]

Renders work/review/review.html — one row per classified slide showing
the PNG (relative link, resolves under file:// when the sheet is opened
locally), slide_id, deterministic score, anchor grade, slide role,
claim context and craft tags — grouped by cluster when
work/clusters.jsonl exists, else by deck. Every row carries a checkbox
plus the plain slide_id text so a reviewer can copy approved ids into
approved.txt; --apply merges the approved slides' index/score/
classification records into work/review/approved.jsonl.

Design: plain stdlib html generation (html.escape + string building,
no deps); JSONL reads reuse corpus.classify._read_jsonl (torn-last-line
tolerant). Pure row/group builders are separated from file IO.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python corpus/review.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus.classify import _read_jsonl

_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:16px;background:#fafafa;
color:#222}
h1{font-size:18px}
h2{margin:24px 0 8px;font-size:15px;border-bottom:1px solid #ccc}
.row{display:flex;gap:12px;align-items:flex-start;background:#fff;
border:1px solid #ddd;border-radius:6px;padding:8px;margin:6px 0}
.row img{width:360px;max-width:45vw;border:1px solid #ccc}
.meta{font-size:13px;line-height:1.6}
code.sid{font-size:13px;background:#eef;padding:1px 4px}
.tags{color:#555}
"""


# --- pure builders -----------------------------------------------------------

def build_rows(work: Path) -> list[dict]:
    """One merged dict per classified slide: index + score + class."""
    index = {r.get("slide_id"): r
             for r in _read_jsonl(work / "index.jsonl")}
    scores = {r.get("slide_id"): r
              for r in _read_jsonl(work / "scores.jsonl")}
    rows = []
    for c in _read_jsonl(work / "classified.jsonl"):
        sid = c.get("slide_id")
        rows.append({"slide_id": sid, "index": index.get(sid, {}),
                     "score": scores.get(sid, {}), "cls": c})
    return rows


def group_rows(work: Path,
               rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """(heading, rows) groups: by cluster when clusters.jsonl exists,
    else by deck; cluster-less slides fall into 'unclustered'."""
    clusters = _read_jsonl(work / "clusters.jsonl")
    if clusters:
        by_id = {r["slide_id"]: r for r in rows}
        groups: list[tuple[str, list[dict]]] = []
        seen: set[str] = set()
        for c in clusters:
            members = [by_id[s] for s in c.get("slide_ids", [])
                       if s in by_id]
            seen.update(r["slide_id"] for r in members)
            if members:
                groups.append((f"cluster {c.get('cluster_id')}", members))
        rest = [r for r in rows if r["slide_id"] not in seen]
        if rest:
            groups.append(("unclustered", rest))
        return groups
    by_deck: dict[str, list[dict]] = {}
    for r in rows:
        by_deck.setdefault(str(r["index"].get("deck_id", "?")),
                           []).append(r)
    return [(f"deck {d}", by_deck[d]) for d in sorted(by_deck)]


def _img_src(png_path: str, out_dir: Path) -> str:
    if not png_path:
        return ""
    p = Path(png_path)
    try:
        # Relative so the sheet keeps working when work/ moves; the
        # browser resolves it under file:// next to review.html.
        return os.path.relpath(p, out_dir).replace("\\", "/")
    except ValueError:  # different drive on Windows
        return p.resolve().as_uri()


def _row_html(row: dict, out_dir: Path) -> str:
    c = row["cls"]
    sid = html.escape(str(row["slide_id"]))
    src = html.escape(_img_src(row["index"].get("png_path", ""),
                               out_dir))
    score = html.escape(str(row["score"].get("score", "-")))
    tags = html.escape(", ".join(c.get("craft_elements") or [])) or "-"
    return (
        '<div class="row">'
        f'<a href="{src}"><img loading="lazy" src="{src}"></a>'
        '<div class="meta">'
        f'<label><input type="checkbox"> '
        f'<code class="sid">{sid}</code></label><br>'
        f'det score: {score} | '
        f'anchor: {html.escape(str(c.get("anchor", "?")))} | '
        f'role: {html.escape(str(c.get("slide_role", "?")))} | '
        f'context: {html.escape(str(c.get("claim_context", "?")))}<br>'
        f'<span class="tags">tags: {tags}</span>'
        '</div></div>')


def render_html(groups: list[tuple[str, list[dict]]],
                out_dir: Path) -> str:
    parts = ["<!doctype html><html><head><meta charset='utf-8'>",
             "<title>DeckEngine corpus review</title>",
             f"<style>{_CSS}</style></head><body>",
             "<h1>DeckEngine corpus review</h1>",
             "<p>Copy approved slide ids (one per line) into "
             "approved.txt, then run review.py --apply.</p>"]
    for heading, rows in groups:
        parts.append(f"<h2>{html.escape(heading)}</h2>")
        parts.extend(_row_html(r, out_dir) for r in rows)
    parts.append("</body></html>")
    return "\n".join(parts)


# --- IO ----------------------------------------------------------------------

def run_review(work: str | Path, out: str | Path | None = None) -> dict:
    work = Path(work).resolve()
    out = Path(out) if out else work / "review" / "review.html"
    rows = build_rows(work)
    groups = group_rows(work, rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(groups, out.parent), encoding="utf-8")
    return {"out": str(out), "rows": len(rows), "groups": len(groups)}


def run_apply(work: str | Path, approved_txt: str | Path) -> dict:
    """Merge approved slide ids' records into review/approved.jsonl.
    Rewritten whole each apply so re-applying stays idempotent."""
    work = Path(work).resolve()
    ids = []
    seen: set[str] = set()  # dedupe: a pasted-twice id must not yield
    for line in Path(approved_txt).read_text(  # two approved lines
            encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in seen:
            seen.add(line)
            ids.append(line)
    index = {r.get("slide_id"): r
             for r in _read_jsonl(work / "index.jsonl")}
    scores = {r.get("slide_id"): r
              for r in _read_jsonl(work / "scores.jsonl")}
    cls = {r.get("slide_id"): r
           for r in _read_jsonl(work / "classified.jsonl")}
    out = work / "review" / "approved.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for sid in ids:
            merged = dict(index.get(sid, {}))
            merged["slide_id"] = sid
            merged["det_score"] = scores.get(sid, {}).get("score")
            merged["score_parts"] = scores.get(sid, {}).get("parts")
            merged["classification"] = cls.get(sid)
            f.write(json.dumps(merged, ensure_ascii=False) + "\n")
    return {"out": str(out), "approved": len(ids)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Generate the corpus review contact sheet.")
    ap.add_argument("--work",
                    default=str(Path(__file__).resolve().parent / "work"),
                    help="derived-data dir (default: corpus/work)")
    ap.add_argument("--out", default=None,
                    help="html path (default: work/review/review.html)")
    ap.add_argument("--apply", default=None, metavar="APPROVED_TXT",
                    help="merge approved slide ids into approved.jsonl")
    args = ap.parse_args(argv)
    if args.apply:
        summary = run_apply(args.work, args.apply)
    else:
        summary = run_review(args.work, args.out)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()

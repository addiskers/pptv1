"""The emphasis contract — the "Indonesia" fix.

The evaluator's sharpest finding: "the title said Indonesia is the best
market, with a table comparing all markets — but visually NOTHING
highlighted Indonesia." This check makes that structurally impossible:
when a slide's title names exactly ONE entity that appears among a
comparative component's labels and no emphasis is set, it becomes a
repair problem.

Discipline (the PlainStr lesson generalized):
- candidates come from LABEL vocabulary only (categories, headers, group
  labels, first cells, stage labels, card titles) — never numeric cells;
- fires only on an UNAMBIGUOUS single match (two entities in the title →
  skip; ambiguity never enters the repair loop);
- every repair sentence names a field that exists on that component and
  offers null as a legal exit;
- a set-but-unmatched highlight gets the inverse check with the exact
  legal values.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from ..schema.rich import plain

_STOP = frozenset({
    "total", "other", "others", "overall", "average", "market", "markets",
    "growth", "share", "revenue", "global", "india", "world", "company",
    "companies", "segment", "segments", "all", "the", "and", "value",
})
_MIN_LEN = 3

# component kind -> (emphasis field, label extractor over the dump dict)
_CAPABLE: dict[str, tuple[str, str]] = {
    "native_chart": ("highlight", "categories"),
    "mini_table": ("highlight_row", "rows0"),
    "data_table": ("highlight_row", "table_rows0"),
    "comparison_columns": ("highlight_column", "headers"),
    "kpi_card_strip": ("highlight_index", "card_titles"),
    "funnel": ("highlight_index", "stage_labels"),
    "chevron_pathway": ("highlight_index", "steps"),
    "matrix_2x2": ("highlight", "quadrant_titles"),
}


def _labels(kind: str, d: dict) -> list[str]:
    if kind == "native_chart":
        return list(d.get("categories") or []) + \
            [s.get("name", "") for s in d.get("series") or []]
    if kind == "mini_table":
        return [str(r[0]) for r in d.get("rows") or [] if r]
    if kind == "data_table":
        out = [g.get("label", "") for g in d.get("groups") or []]
        for g in d.get("groups") or []:
            out += [str(r[0]) for r in g.get("rows") or [] if r]
        return out
    if kind == "comparison_columns":
        return [c.get("header", "") for c in d.get("columns") or []]
    if kind == "kpi_card_strip":
        return [plain(c.get("title", "")) for c in d.get("cards") or []]
    if kind == "funnel":
        return [s.get("label", "") for s in d.get("stages") or []]
    if kind == "chevron_pathway":
        return list(d.get("steps") or [])
    if kind == "matrix_2x2":
        return [q.get("title", "") for q in d.get("quadrants") or []]
    return []


def _walk_capable(node) -> list[dict]:
    out = []
    if isinstance(node, dict):
        if node.get("kind") in _CAPABLE:
            out.append(node)
        else:
            for v in node.values():
                out.extend(_walk_capable(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_capable(v))
    return out


def _title_matches(title: str, labels: list[str]) -> list[str]:
    t = plain(title).casefold()
    hits = []
    for lb in labels:
        lb_p = plain(str(lb)).strip()
        if len(lb_p) < _MIN_LEN or lb_p.casefold() in _STOP:
            continue
        if re.search(r"(?<!\w)" + re.escape(lb_p.casefold()) + r"(?!\w)", t):
            hits.append(lb_p)
    # dedupe preserving order
    seen: set[str] = set()
    return [h for h in hits if not (h.casefold() in seen
                                    or seen.add(h.casefold()))]


def check_slide_emphasis(slide: BaseModel) -> list[str]:
    """Emphasis problems for one slide (deterministic, free). Fires only
    on an unambiguous single title-entity match with no emphasis set."""
    title = getattr(slide, "title", "") or ""
    if not plain(title).strip():
        return []
    problems: list[str] = []
    for d in _walk_capable(slide.model_dump()):
        kind = d["kind"]
        field, _ = _CAPABLE[kind]
        current = d.get(field)
        labels = _labels(kind, d)
        if current not in (None, ""):
            # inverse check: a set NAME must match a real label
            if isinstance(current, str) and not any(
                    plain(str(lb)).strip().casefold() == current.strip().casefold()
                    for lb in labels):
                legal = ", ".join(repr(plain(str(x)).strip())
                                  for x in labels[:5])
                problems.append(
                    f"{kind}.{field}={current!r} matches none of its "
                    f"labels ({legal}...): use an exact label or null")
            continue
        hits = _title_matches(title, labels)
        if len(hits) != 1:
            continue  # zero or ambiguous: never a repair problem
        entity = hits[0]
        if field == "highlight_index":
            idx = next((i for i, lb in enumerate(labels)
                        if plain(str(lb)).strip().casefold()
                        == entity.casefold()), None)
            problems.append(
                f"the title names {entity!r}, which is item {idx} of the "
                f"{kind}, but nothing is emphasized: set {field}={idx} so "
                f"the eye lands on the claim's subject, or retitle if "
                f"{entity!r} is not the point")
        else:
            problems.append(
                f"the title names {entity!r}, which appears in the "
                f"{kind}'s labels, but nothing is emphasized: set "
                f"{field}={entity!r} so the eye lands on the claim's "
                f"subject (or null it and retitle if {entity!r} is not "
                f"the point)")
        if len(problems) >= 3:
            break
    return problems

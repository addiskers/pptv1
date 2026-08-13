"""Provenance enforcement — the marker system (no-CSV mode).

The evaluated deck drowned in "illustrative" (33 hits) because our own
prompt demanded it. The winning deck instead marked every figure:
● official / ◐ reconstructed / ○ composite, plus a methodology slide.
This module is the deterministic floor under the new policy:

- PROSE TIER: every non-benign numeral in a marker-capable (RichStr)
  field needs a [[src:official]] / [[src:recon]] / [[src:est]] token
  within 24 characters after it.
- TABULAR TIER: chart series / table rows / stat displays are PlainStr —
  markup would be stripped, so markers are NEVER demanded inline there
  (an unfixable repair loop). Instead the slide's footnote must carry a
  marked source line (e.g. "Source: FAOSTAT 2025 [[src:official]]").
- The word "illustrative" is BANNED outright — a repair problem.

Runs ONLY when no FACTS table exists; CSV mode keeps verify_spec_numbers'
strictness (CSV facts are ● by construction). Mirrors writing.py: pure
functions returning repair-loop sentences.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from .facts import _NUM, is_benign

_MARKER = re.compile(r"\[\[src:(official|recon|est)\]\]")
_WINDOW = 24  # chars after a numeral in which its marker must appear
_BANNED = re.compile(r"illustrative", re.IGNORECASE)

# keys whose values are RichStr prose in EVERY model that declares them
# (guarded by tests/test_provenance.py::test_marker_keys_are_rich_everywhere;
# 'label' is deliberately absent — it is PlainStr on funnel/timeline/legend)
MARKER_KEYS = frozenset({
    "title", "subtitle", "text", "body", "heading", "takeaway", "stat",
    "segments", "left", "right", "footnote",
})

# PlainStr / numeric payloads: presence of a non-benign figure here demands
# a marked source in the footnote instead of inline markers
_TABULAR_KEYS = frozenset({
    "values", "rows", "display", "value", "center_text", "categories",
})

_SKIP_KEYS = frozenset({
    "slide_type", "kind", "icon", "fill_role", "color_role", "size_role",
    "align", "chart_type", "sort", "style", "date", "src", "bg_image",
    "value_suffix", "number", "code",
})


def _walk(node, key: str | None = None):
    """Yield (key, string) pairs across the dumped spec tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _SKIP_KEYS:
                continue
            yield from _walk(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)
    elif isinstance(node, str) and key is not None:
        yield key, node
    elif isinstance(node, (int, float)) and key is not None:
        yield key, str(node)


def _unmarked_figures(text: str) -> list[str]:
    """Non-benign numerals lacking a marker token within the window."""
    out = []
    for m in _NUM.finditer(text):
        window = text[max(0, m.start() - 16):m.end() + 16]
        if is_benign(m.group(), window):
            continue
        after = text[m.end():m.end() + _WINDOW + len("[[src:official]]")]
        if not _MARKER.search(after):
            out.append(m.group())
    return out


def check_slide_markers(slide: BaseModel) -> list[str]:
    """Marker problems for one slide spec (deterministic, free). Call ONLY
    when facts is None — CSV mode has its own verification."""
    problems: list[str] = []
    dump = slide.model_dump()

    joined = "\n".join(t for _, t in _walk(dump))
    if _BANNED.search(joined):
        problems.append(
            "the word 'illustrative' is banned — use the best real-world "
            "figure you know and mark it: [[src:official]] if verified, "
            "[[src:recon]] if reconstructed from known anchors, [[src:est]] "
            "if your own estimate")

    tabular_hit = False
    for key, text in _walk(dump):
        if key in MARKER_KEYS:
            for fig in _unmarked_figures(text)[:3]:
                problems.append(
                    f"figure '{fig}' in {key!r} has no provenance marker — "
                    f"append [[src:official]], [[src:recon]] or [[src:est]] "
                    f"immediately after it")
        elif key in _TABULAR_KEYS and not tabular_hit:
            nums = [m.group() for m in _NUM.finditer(text)
                    if not is_benign(m.group(), text)]
            if nums:
                tabular_hit = True
    if tabular_hit:
        foot = dump.get("footnote") or ""
        if not _MARKER.search(foot):
            problems.append(
                "chart/table figures need a marked source: end the footnote "
                "with e.g. 'Source: <best-known source, year> "
                "[[src:official]]' (or [[src:recon]]/[[src:est]] to match "
                "how the numbers were derived)")
    return problems


def marker_coverage(slide: BaseModel) -> tuple[int, int]:
    """(marked, total) non-benign figures in prose fields — logged per deck
    so compliance is observable."""
    marked = total = 0
    for key, text in _walk(slide.model_dump()):
        if key not in MARKER_KEYS:
            continue
        for m in _NUM.finditer(text):
            window = text[max(0, m.start() - 16):m.end() + 16]
            if is_benign(m.group(), window):
                continue
            total += 1
            after = text[m.end():m.end() + _WINDOW + len("[[src:official]]")]
            if _MARKER.search(after):
                marked += 1
    return marked, total


def collect_marked_figures(slides: list[BaseModel]) -> list[dict]:
    """Every ◐/○ figure with its slide index and context — feeds the auto
    methodology slide (● excluded: official needs no explanation)."""
    rows: list[dict] = []
    for idx, slide in enumerate(slides, start=1):
        for key, text in _walk(slide.model_dump()):
            for m in _MARKER.finditer(text):
                tier = m.group(1)
                if tier == "official":
                    continue
                before = text[:m.start()]
                num = None
                for n in _NUM.finditer(before):
                    if m.start() - n.end() <= _WINDOW:
                        num = n.group()
                if num is None:
                    continue
                ctx = re.sub(r"\[\[.*?\]\]|\*", "",
                             before[-60:]).strip()
                rows.append({"figure": num, "tier": tier, "slide": idx,
                             "context": ctx})
    return rows

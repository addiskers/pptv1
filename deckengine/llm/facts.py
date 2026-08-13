"""Fact tables: numbers are computed deterministically in Python, never by the LLM.

The LLM receives the fact list (id + display + description + source) in its
prompt and may only use those display values. After generation,
verify_spec_numbers() sweeps every numeral in the spec (including structured
fields — chart series, table cells, stat values, via the JSON dump) and flags
anything unverified. The derivation library computes the comparisons consulting
prose actually needs (deltas, shares, multiples, CAGRs) so strict enforcement
doesn't starve the prose.

Review finding closed here: integers 0-100 were blanket-benign, exempting every
market share and CAGR — the numbers a research firm is liable for. Now only
small counts (0-12) and years are benign, and NOTHING adjacent to %/share/
growth/CAGR context is ever benign.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from statistics import mean


@dataclass
class Fact:
    id: str
    display: str        # exact string the LLM must use, e.g. "$1,216" / "+2.7%"
    description: str
    source: str = ""    # provenance label, e.g. "skyquest_ev_2026.csv row 12"


@dataclass
class FactTable:
    facts: dict[str, Fact] = field(default_factory=dict)

    def add(self, id: str, display: str, description: str,
            source: str = "") -> None:
        self.facts[id] = Fact(id, display, description, source)

    # -- derivation library: consulting math, computed here, never by LLM ----

    def derive_pct_delta(self, id: str, a: float, b: float, description: str,
                         source: str = "", decimals: int = 1) -> None:
        """'X is 2.7% more than Y' — the classic client-facing delta."""
        delta = (a - b) / b * 100 if b else 0.0
        self.add(id, f"{delta:+.{decimals}f}%", description, source)

    def derive_share(self, id: str, part: float, total: float,
                     description: str, source: str = "",
                     decimals: int = 0) -> None:
        share = part / total * 100 if total else 0.0
        self.add(id, f"{share:.{decimals}f}%", description, source)

    def derive_multiple(self, id: str, a: float, b: float, description: str,
                        source: str = "", decimals: int = 1) -> None:
        mult = a / b if b else 0.0
        self.add(id, f"{mult:.{decimals}f}x", description, source)

    def derive_cagr(self, id: str, start: float, end: float, years: float,
                    description: str, source: str = "",
                    decimals: int = 1) -> None:
        cagr = ((end / start) ** (1 / years) - 1) * 100 \
            if start > 0 and years > 0 else 0.0
        self.add(id, f"{cagr:.{decimals}f}%", description, source)

    def derive_rank(self, id: str, name: str, values: dict[str, float],
                    description: str, source: str = "") -> None:
        order = sorted(values, key=values.get, reverse=True)
        self.add(id, f"#{order.index(name) + 1}", description, source)

    # -- ingestion -----------------------------------------------------------

    @classmethod
    def from_csv(cls, text: str, source_label: str = "uploaded CSV") -> "FactTable":
        """Column aggregates + per-row values, each fact tagged with provenance."""
        table = cls()
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return table
        for col in rows[0].keys():
            vals = []
            for r in rows:
                try:
                    vals.append(float(str(r[col]).replace(",", "")
                                      .replace("$", "").replace("%", "")))
                except (TypeError, ValueError):
                    continue
            if not vals or len(vals) < len(rows) // 2:
                continue
            slug = re.sub(r"\W+", "_", col.strip().lower())
            src = f"{source_label} · column '{col}'"
            table.add(f"{slug}_sum", _fmt(sum(vals)), f"sum of {col}", src)
            table.add(f"{slug}_avg", _fmt(mean(vals)), f"average of {col}", src)
            table.add(f"{slug}_min", _fmt(min(vals)), f"minimum of {col}", src)
            table.add(f"{slug}_max", _fmt(max(vals)), f"maximum of {col}", src)
            total = sum(vals)
            if total > 0 and len(vals) == len(rows):
                label_col = next(iter(rows[0]))
                for i, r in enumerate(rows):
                    try:
                        v = float(str(r[col]).replace(",", "")
                                  .replace("$", "").replace("%", ""))
                    except (TypeError, ValueError):
                        continue
                    table.derive_share(
                        f"row{i}_{slug}_share", v, total,
                        f"{r.get(label_col, f'row {i}')} share of total {col}",
                        f"{source_label} · row {i}")
        label_col = next(iter(rows[0]))
        for i, r in enumerate(rows):
            for col, v in r.items():
                slug = re.sub(r"\W+", "_", col.strip().lower())
                table.add(f"row{i}_{slug}", str(v).strip(),
                          f"{col} of {r.get(label_col, f'row {i}')}",
                          f"{source_label} · row {i}")
        return table

    # -- verification --------------------------------------------------------

    def whitelist(self) -> set[str]:
        out: set[str] = set()
        for f in self.facts.values():
            for tok in _NUM.findall(f.display):
                out.add(_canon(tok))
        return out

    def prompt_block(self, limit: int = 400) -> str:
        lines = [f"- {f.id}: {f.display}  ({f.description})"
                 for f in list(self.facts.values())[:limit]]
        return "FACTS (use these display values verbatim; do not compute or "\
               "invent any other numbers):\n" + "\n".join(lines)

    def used_facts(self, spec_text: str) -> list[Fact]:
        """Facts whose display numerals appear in the spec — the sources list."""
        spec_tokens = {_canon(t) for t in _NUM.findall(spec_text)}
        used = []
        for f in self.facts.values():
            toks = {_canon(t) for t in _NUM.findall(f.display)}
            if toks and toks <= spec_tokens:
                used.append(f)
        return used


_NUM = re.compile(r"\d[\d,]*\.?\d*")
# ONLY small counts are inherently benign (bullet counts, phases, quarters).
# The old 0-100 window exempted every share and CAGR — closed per review.
_BENIGN_MAX = 12
# a number in this context is NEVER benign, whatever its size
_RISK_CONTEXT = re.compile(
    r"%|percent|share|cagr|growth|margin|rate|yoy|y/y|\bbps\b", re.IGNORECASE)


def _canon(tok: str) -> str:
    return tok.replace(",", "").rstrip(".")


def _fmt(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.1f}"


def verify_spec_numbers(spec_text: str, table: FactTable) -> list[str]:
    """Numerals in the spec that are neither whitelisted nor genuinely benign."""
    wl = table.whitelist()
    suspects = []
    for m in _NUM.finditer(spec_text):
        tok = m.group()
        if _canon(tok) in wl:
            continue
        window = spec_text[max(0, m.start() - 16):m.end() + 16]
        if is_benign(tok, window):
            continue
        suspects.append(tok)
    return sorted(set(suspects))


def _try_int(s: str) -> int:
    try:
        f = float(s)
        return int(f) if f == int(f) else -1
    except ValueError:
        return -1


def is_benign(tok: str, context: str) -> bool:
    """Small counts (0-12) and years are benign — UNLESS the surrounding
    context smells of %/share/growth/CAGR, which is never benign. Shared by
    verify_spec_numbers (CSV mode) and provenance checks (no-CSV mode)."""
    if _RISK_CONTEXT.search(context):
        return False
    iv = _try_int(_canon(tok))
    return (0 <= iv <= _BENIGN_MAX) or (1900 <= iv <= 2100)

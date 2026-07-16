"""Fact tables: numbers are computed deterministically in Python, never by the LLM.

The LLM receives the rendered fact list (id + display + description) in its
prompt and is told to only use those display strings. After generation,
verify_spec_numbers() sweeps every numeral in the spec and flags any number that
is not in the whitelist — the enforcement mechanism the prompt rule lacks.
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


@dataclass
class FactTable:
    facts: dict[str, Fact] = field(default_factory=dict)

    def add(self, id: str, display: str, description: str) -> None:
        self.facts[id] = Fact(id, display, description)

    def derive_pct_delta(self, id: str, a: float, b: float, description: str,
                         decimals: int = 1) -> None:
        """The classic '$1,216 is 2.7% more than $1,183' — computed here, not by the LLM."""
        delta = (a - b) / b * 100 if b else 0.0
        self.add(id, f"{delta:+.{decimals}f}%", description)

    @classmethod
    def from_csv(cls, text: str) -> "FactTable":
        """Basic per-numeric-column aggregates. Extend with domain derivations."""
        table = cls()
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return table
        for col in rows[0].keys():
            vals = []
            for r in rows:
                try:
                    vals.append(float(str(r[col]).replace(",", "").replace("$", "")))
                except (TypeError, ValueError):
                    continue
            if not vals or len(vals) < len(rows) // 2:
                continue
            slug = re.sub(r"\W+", "_", col.strip().lower())
            table.add(f"{slug}_sum", _fmt(sum(vals)), f"sum of {col}")
            table.add(f"{slug}_avg", _fmt(mean(vals)), f"average of {col}")
            table.add(f"{slug}_min", _fmt(min(vals)), f"minimum of {col}")
            table.add(f"{slug}_max", _fmt(max(vals)), f"maximum of {col}")
        for i, r in enumerate(rows):
            for col, v in r.items():
                slug = re.sub(r"\W+", "_", col.strip().lower())
                table.add(f"row{i}_{slug}", str(v).strip(), f"{col} of row {i}")
        return table

    def whitelist(self) -> set[str]:
        """All numeric tokens that may legitimately appear in a spec."""
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


_NUM = re.compile(r"\d[\d,]*\.?\d*")
_BENIGN = {str(x) for x in range(0, 101)} | {"2x", "3x"}


def _canon(tok: str) -> str:
    return tok.replace(",", "").rstrip(".")


def _fmt(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.1f}"


def verify_spec_numbers(spec_text: str, table: FactTable) -> list[str]:
    """Return numerals in the spec that are in neither the fact whitelist nor
    benign (years, small integers). Route violations to the repair loop."""
    wl = table.whitelist()
    suspects = []
    for tok in _NUM.findall(spec_text):
        c = _canon(tok)
        if c in wl or c in _BENIGN:
            continue
        if 1900 <= _try_int(c) <= 2100:  # years
            continue
        suspects.append(tok)
    return sorted(set(suspects))


def _try_int(s: str) -> int:
    try:
        return int(float(s))
    except ValueError:
        return -1

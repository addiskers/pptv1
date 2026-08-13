"""Semantic colour lexicon — red = stress, amber = watch, green = healthy.

The winning deck coloured by MEANING (overdrawn basins red, safe ones
green); ours coloured by position. This is the dependency-free lexicon
plus the guard that keeps it honest: a mapping only applies when at least
TWO labels match at least TWO DISTINCT buckets — one stray word never
recolours a chart.
"""
from __future__ import annotations

import re

NEGATIVE = frozenset({
    "risk", "risky", "stress", "stressed", "decline", "declining",
    "deficit", "loss", "losses", "critical", "severe", "depleted",
    "overdrawn", "overexploited", "falling", "weak", "unhealthy",
    "shortfall", "negative", "worst", "lagging", "distress", "distressed",
    "unsafe", "failing",
})
WARNING = frozenset({
    "moderate", "watch", "watchlist", "mixed", "partial", "partially",
    "stagnant", "flat", "marginal", "medium", "caution", "borderline",
    "uneven", "semi", "transitional", "emerging",
})
POSITIVE = frozenset({
    "healthy", "strong", "growth", "growing", "improving", "improved",
    "surplus", "rising", "robust", "recovering", "positive", "best",
    "leading", "safe", "stable", "thriving", "sound",
})

_BUCKET_ROLE = {"negative": "negative", "warning": "warning",
                "positive": "positive"}


def bucket(label: str) -> str | None:
    """Semantic bucket for one label, or None. Ambiguous labels (tokens in
    more than one bucket) return None — never guess."""
    tokens = set(re.findall(r"[a-z]+", label.lower()))
    hits = {name for name, words in (("negative", NEGATIVE),
                                     ("warning", WARNING),
                                     ("positive", POSITIVE))
            if tokens & words}
    return hits.pop() if len(hits) == 1 else None


def rag_map(labels: list[str]) -> dict[str, str] | None:
    """{label -> theme colour role} when the set genuinely reads as a RAG
    scale: >=2 labels matched across >=2 DISTINCT buckets. Else None."""
    buckets = {lb: bucket(lb) for lb in labels}
    matched = [b for b in buckets.values() if b]
    if len(matched) < 2 or len(set(matched)) < 2:
        return None
    return {lb: _BUCKET_ROLE[b] for lb, b in buckets.items() if b}

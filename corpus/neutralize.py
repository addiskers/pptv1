"""Neutralize an induced spec so no client IP travels into the library.

Two layers:
1. neutralize_spec() — ONE text LLM call rewrites the spec to a fictional,
   internally-consistent topic: real company/place names become invented
   ones, every number becomes a round plausible value that PRESERVES
   relative order (so sort/highlight/deltas still make sense). The LLM call
   is a module attribute so tests monkeypatch it.
2. leak_gate() — DETERMINISTIC and non-overridable: extract the specific
   proper nouns and specific numbers from the SOURCE slide text and assert
   none survive in the neutralized spec. A single overlap fails the gate;
   the induced exemplar is dropped, never force-applied.

The engine never ships corpus imagery or text — only structure and
measurements, which are uncopyrightable facts. This module is the gate that
guarantees it.
"""
from __future__ import annotations

import json
import re

# numbers worth protecting: has a comma/decimal, or >=4 digits — i.e. a
# specific figure, not a small count. Years (1900-2100) are excluded as
# non-identifying.
_SPECIFIC_NUM = re.compile(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{3})+|\d{4,}")
# proper-noun phrases: runs of Capitalized words
_PROPER = re.compile(r"\b[A-Z][a-zA-Z&.'-]+(?:\s+[A-Z][a-zA-Z&.'-]+)*")

# Vocabulary that is NOT identifying — it appears in both source and
# neutralized text legitimately (common English + business/industry topic
# words + the neutralizer keeps the INDUSTRY, only names/numbers change).
# A leak is a DISTINCTIVE name or a SPECIFIC number, not a topic noun, so
# this list is deliberately broad to keep precision high.
_STOP = {
    # function / very common English
    "the", "a", "an", "and", "or", "of", "in", "to", "for", "with", "by",
    "on", "at", "as", "is", "are", "was", "were", "be", "been", "this",
    "that", "these", "those", "it", "its", "they", "them", "their", "we",
    "our", "you", "your", "he", "she", "his", "her", "will", "would", "can",
    "could", "should", "may", "might", "must", "not", "no", "yes", "but",
    "however", "therefore", "thus", "while", "when", "where", "which",
    "who", "what", "how", "why", "all", "any", "each", "every", "some",
    "many", "most", "more", "less", "few", "several", "both", "than",
    "then", "also", "only", "over", "under", "up", "down", "out", "into",
    "from", "about", "across", "between", "through", "during", "after",
    "before", "next", "last", "first", "second", "third", "one", "two",
    "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "billion", "million", "thousand", "hundred", "percent",
    # business / consulting vocabulary
    "market", "markets", "revenue", "revenues", "growth", "share", "shares",
    "cost", "costs", "price", "pricing", "margin", "margins", "ebitda",
    "cagr", "total", "value", "values", "volume", "volumes", "segment",
    "segments", "region", "regions", "north", "south", "east", "west",
    "global", "national", "international", "domestic", "local", "product",
    "products", "service", "services", "sales", "customer", "customers",
    "channel", "channels", "demand", "supply", "capacity", "profit",
    "profits", "loss", "losses", "investment", "investments", "return",
    "returns", "capital", "assets", "operations", "operating", "business",
    "businesses", "company", "companies", "industry", "industries",
    "sector", "sectors", "competition", "competitive", "competitor",
    "competitors", "strategy", "strategic", "analysis", "opportunity",
    "opportunities", "risk", "risks", "trend", "trends", "forecast",
    "outlook", "performance", "productivity", "efficiency", "quality",
    "innovation", "technology", "digital", "platform", "solutions",
    "management", "leadership", "team", "teams", "employee", "employees",
    "staff", "workforce", "board", "executive", "executives",
    "requirements", "survey", "report", "data", "insights", "findings",
    "benchmark", "adoption", "transformation", "generative", "ai",
    "q1", "q2", "q3", "q4", "fy", "usd", "inr", "eur", "gbp", "mn", "bn",
    "yoy", "exhibit", "source", "note", "notes", "figure", "chart",
    "table", "overview", "summary", "key", "other", "others", "top",
    "new", "current", "future", "increase", "decrease", "improve",
    "reduce", "grow", "scale", "drive", "deliver", "enable", "support",
    # common industry topic nouns (the neutralizer keeps the industry)
    "banking", "bank", "banks", "finance", "financial", "insurance",
    "retail", "healthcare", "pharma", "pharmaceutical", "energy", "oil",
    "gas", "automotive", "manufacturing", "agriculture", "tourism",
    "travel", "travellers", "travelers", "visitor", "visitors",
    "hospitality", "telecom", "media", "consumer", "enterprise", "public",
    "government", "education", "logistics", "transport", "mobility",
    "convention", "designation", "winning",
}


def _tokens(text: str) -> tuple[set[str], set[str]]:
    """Specific proper nouns (lowercased words) and specific numbers."""
    nums = {_canon_num(m.group()) for m in _SPECIFIC_NUM.finditer(text)}
    nums = {n for n in nums if not _is_year(n)}
    props: set[str] = set()
    for m in _PROPER.finditer(text):
        for w in re.findall(r"[A-Za-z][A-Za-z&']*", m.group()):
            lw = w.strip(".'-&").lower()  # drop trailing punctuation
            # a leak is a DISTINCTIVE name: >=4 chars and not a common word
            if len(lw) >= 4 and lw not in _STOP:
                props.add(lw)
    return props, nums


def _canon_num(tok: str) -> str:
    return tok.replace(",", "").rstrip(".")


def _is_year(canon: str) -> bool:
    try:
        return 1900 <= int(float(canon)) <= 2100
    except ValueError:
        return False


def _spec_text(node) -> str:
    """Concatenate every string value in a spec dict tree."""
    out: list[str] = []
    if isinstance(node, dict):
        for v in node.values():
            out.append(_spec_text(v))
    elif isinstance(node, list):
        for v in node:
            out.append(_spec_text(v))
    elif isinstance(node, str):
        out.append(node)
    return " ".join(out)


def leak_gate(neutralized: dict, source_text: str) -> list[str]:
    """Return the list of source-specific tokens that survived into the
    neutralized spec. Empty list == clean (safe to keep)."""
    src_props, src_nums = _tokens(source_text)
    neu_text = _spec_text(neutralized)
    neu_props, neu_nums = _tokens(neu_text)
    leaked = sorted((src_props & neu_props) | (src_nums & neu_nums))
    return leaked


# --- LLM rewrite (module attribute; monkeypatched in tests) ------------------

_NEUTRALIZE_PROMPT = """You are given a slide spec (JSON) reverse-engineered from a consulting slide. Rewrite it into a FICTIONAL, internally-consistent example so it carries NO real client content.

Rules:
- Replace every real company, product, person and place name with invented ones (e.g. "Acme", "Northwind", "Zephyr"). Keep them consistent within the spec.
- Replace every number with a round, plausible value that PRESERVES the relative order and rough ratios of the originals (if A > B in the source, keep A > B). Prefer clean numbers.
- Keep the STRUCTURE, component types, layout, chart_type, styling and word counts identical — only the topic and values change.
- Return ONLY the rewritten JSON object, same schema, no prose."""


def _neutralize_call(spec: dict) -> dict:
    """ONE text LLM call. Module attribute so tests can monkeypatch."""
    from deckengine.llm.spec_generator import model_id, provider
    payload = _NEUTRALIZE_PROMPT + "\n\nSPEC:\n" + json.dumps(spec)
    if provider() == "openai":
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model_id(), max_completion_tokens=6000,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": payload}])
        return json.loads(resp.choices[0].message.content)
    import anthropic
    client = anthropic.Anthropic()
    schema = {"type": "object", "additionalProperties": True}
    resp = client.messages.create(
        model=model_id(), max_tokens=6000,
        tools=[{"name": "emit_spec", "description": "Emit the rewritten spec.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": "emit_spec"},
        messages=[{"role": "user", "content": payload}])
    return next(b.input for b in resp.content if b.type == "tool_use")


def neutralize_spec(spec: dict, source_text: str,
                    slide_type: str) -> tuple[dict | None, list[str]]:
    """Rewrite + gate. Returns (neutralized_spec, leaked_tokens). When
    leaked is non-empty the spec is UNSAFE and neutralized_spec is None."""
    out = _neutralize_call(spec)
    out.setdefault("slide_type", slide_type)
    leaked = leak_gate(out, source_text)
    if leaked:
        return None, leaked
    return out, []

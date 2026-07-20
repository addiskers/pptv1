"""Rich text in specs is markdown-lite:
  **bold**, *italic*, [[role]]colored[[/]],
  [[hl]]highlighted[[/]]  -> coloured pill behind the run (consulting emphasis),
  ^1  or  ^{12}           -> superscript footnote reference.

LLMs write these reliably; the engine parses them into styled Spans once, at the
schema boundary, so measurement and rendering always agree on styling.
"""
from __future__ import annotations

import re

from ..core.fit_text import Span

_TOKEN = re.compile(
    r"(\*\*(?P<bold>.+?)\*\*)"
    r"|(\*(?P<italic>[^*\s](?:[^*]*?[^*\s])?)\*)"
    r"|(\[\[(?P<role>[a-z_&A-Z]+)\]\](?P<colored>.+?)\[\[/\]\])"
    r"|(\^(?P<sup>\d+|\{[^}]+\}))",
    re.DOTALL,
)


def parse_rich(text: str, *, base_color_role: str | None = None) -> list[Span]:
    spans: list[Span] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        if m.start() > pos:
            spans.append(Span(text[pos:m.start()], color_role=base_color_role))
        if m.group("bold") is not None:
            spans.append(Span(m.group("bold"), bold=True, color_role=base_color_role))
        elif m.group("italic") is not None:
            spans.append(Span(m.group("italic"), italic=True, color_role=base_color_role))
        elif m.group("sup") is not None:
            ref = m.group("sup").strip("{}")
            spans.append(Span(ref, superscript=True, color_role=base_color_role))
        else:
            role = m.group("role")
            if role == "hl":  # highlight pill, not a text colour
                spans.append(Span(m.group("colored"), bold=True,
                                  highlight_role="highlight",
                                  color_role=base_color_role))
            else:
                spans.append(Span(m.group("colored"), color_role=role))
        pos = m.end()
    if pos < len(text):
        spans.append(Span(text[pos:], color_role=base_color_role))
    return spans or [Span("")]


def plain(text: str) -> str:
    """Strip markup (for char-count sanity checks)."""
    return "".join(s.text for s in parse_rich(text))

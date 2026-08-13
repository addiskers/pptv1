"""fit_text — the critical utility.

Measures text by shaping it with uharfbuzz against the real TTFs PowerPoint will
use (kerning + OpenType shaping, incl. Devanagari), wraps against a safety-factored
width, and returns explicit line metrics that the renderer writes into the deck as
exact point spacing — line height is a contract we dictate, not an estimate.

The measurement unit is a list of styled Spans, never a bare string: bold runs are
5-8% wider than regular and must be measured with the bold face.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTFont

from .bbox import BBox
from .fonts import FontRegistry, default_registry
from .units import EMU_PER_PT, pt

WRAP_SAFETY = 0.96  # wrap against 96% of writable width; PowerPoint must never wrap earlier
ELLIPSIS = "…"


SUPERSCRIPT_SCALE = 0.65

@dataclass(frozen=True)
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    size_pt: float | None = None      # None -> use the fitted base size
    font: str | None = None           # None -> caller's font family
    color_role: str | None = None     # resolved at render time from Theme
    highlight_role: str | None = None  # theme role of a pill behind the run
    superscript: bool = False          # raised, smaller (footnote refs)

    def sized(self, base: float) -> float:
        s = self.size_pt if self.size_pt is not None else base
        return s * SUPERSCRIPT_SCALE if self.superscript else s


@dataclass
class Line:
    spans: list[Span]
    width_emu: int
    height_emu: int          # line pitch we will dictate via <a:spcPts>


@dataclass
class FitResult:
    size_pt: float           # fitted base size
    lines: list[Line]
    truncated: bool
    height_emu: int          # total consumed height
    line_spacing_pt: float   # exact per-line spacing to write into the paragraph


class TextMeasurer:
    """Shapes text with uharfbuzz; caches faces per TTF path."""

    def __init__(self, registry: FontRegistry | None = None) -> None:
        self.registry = registry or default_registry()

    @staticmethod
    @lru_cache(maxsize=32)
    def _hb_font(path_str: str) -> tuple[hb.Font, int]:
        blob = hb.Blob.from_file_path(path_str)
        face = hb.Face(blob)
        return hb.Font(face), face.upem

    @staticmethod
    @lru_cache(maxsize=32)
    def _line_pitch_em(path_str: str) -> float:
        tt = TTFont(path_str, lazy=True)
        upem = tt["head"].unitsPerEm
        hhea = tt["hhea"]
        pitch = (hhea.ascent - hhea.descent + hhea.lineGap) / upem
        tt.close()
        return max(1.0, pitch)

    def _path_for(self, family: str, bold: bool, italic: bool) -> str:
        return str(self.registry.resolve(family, bold=bold, italic=italic))

    def width_pt(self, text: str, family: str, size_pt: float, *,
                 bold: bool = False, italic: bool = False) -> float:
        if not text:
            return 0.0
        font, upem = self._hb_font(self._path_for(family, bold, italic))
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf, {"kern": True, "liga": True})
        units = sum(p.x_advance for p in buf.glyph_positions)
        return units / upem * size_pt

    def span_width_emu(self, span: Span, family: str, base_size: float) -> int:
        w = self.width_pt(span.text, span.font or family, span.sized(base_size),
                          bold=span.bold, italic=span.italic)
        return round(w * EMU_PER_PT)

    def line_height_emu(self, spans: list[Span], family: str, base_size: float,
                        line_spacing: float = 1.0) -> int:
        """Line pitch = max over spans of (natural font pitch × size × multiplier)."""
        best = 0.0
        for s in spans or [Span("")]:
            path = self._path_for(s.font or family, s.bold, s.italic)
            best = max(best, self._line_pitch_em(path) * s.sized(base_size))
        return pt(best * line_spacing)

    # -- wrapping ---------------------------------------------------------

    _token_re = re.compile(r"\s+|\S+\s*")

    def wrap(self, spans: list[Span], family: str, base_size: float,
             max_width_emu: int, line_spacing: float = 1.0) -> list[Line]:
        """Greedy word-wrap across styled spans. Respects explicit \n breaks."""
        budget = int(max_width_emu * WRAP_SAFETY)
        lines: list[Line] = []
        cur: list[Span] = []
        cur_w = 0

        def flush() -> None:
            nonlocal cur, cur_w
            spans_out = _trim_trailing_ws(cur)
            lines.append(Line(
                spans=spans_out,
                width_emu=sum(self.span_width_emu(s, family, base_size) for s in spans_out),
                height_emu=self.line_height_emu(spans_out, family, base_size, line_spacing),
            ))
            cur, cur_w = [], 0

        # split on explicit \n while keeping span styles
        hard_parts: list[list[Span]] = [[]]
        for span in spans:
            pieces = span.text.split("\n")
            for i, piece in enumerate(pieces):
                if i > 0:
                    hard_parts.append([])
                if piece:
                    hard_parts[-1].append(replace(span, text=piece))

        for part in hard_parts:
            cur, cur_w = [], 0
            for span in part:
                for m in self._token_re.finditer(span.text):
                    if not m.group().strip():
                        # inter-span whitespace: keep it if mid-line (never starts a line)
                        if cur:
                            ws = replace(span, text=m.group())
                            cur.append(ws)
                            cur_w += self.span_width_emu(ws, family, base_size)
                        continue
                    token = replace(span, text=m.group())
                    tw = self.span_width_emu(token, family, base_size)
                    stripped = replace(span, text=m.group().rstrip())
                    sw = self.span_width_emu(stripped, family, base_size)
                    if cur and cur_w + sw > budget:
                        flush()
                    if not cur and sw > budget:
                        # single token wider than the line: keep it WHOLE on
                        # its own over-wide line (next token flushes it).
                        # fit_text treats that as a fit failure (shrink first,
                        # ellipsize only at the size floor) — NEVER a mid-word
                        # split ("Marke/t").
                        cur = [stripped]
                        cur_w = sw
                        continue
                    cur.append(token)
                    cur_w += tw
            flush()
        return lines

    def ellipsize_token(self, span: Span, family: str, base_size: float,
                        budget: int) -> Span:
        """Longest prefix + ellipsis that fits the budget ("Marke…")."""
        text = span.text.rstrip()
        while text:
            cand = replace(span, text=text.rstrip(".,;") + ELLIPSIS)
            if self.span_width_emu(cand, family, base_size) <= budget:
                return cand
            text = text[:-1]
        return replace(span, text=ELLIPSIS)


def _trim_trailing_ws(spans: list[Span]) -> list[Span]:
    out = list(spans)
    while out:
        t = out[-1].text.rstrip()
        if t:
            out[-1] = replace(out[-1], text=t)
            break
        out.pop()
    return out


def fit_text(spans: list[Span], bbox: BBox, family: str, *,
             max_size: float, min_size: float,
             max_lines: int | None = None,
             line_spacing: float = 1.0,
             strategy: str = "shrink_then_truncate",
             measurer: TextMeasurer | None = None) -> FitResult:
    """Try max_size; shrink in 0.5pt steps to min_size; then truncate with ellipsis."""
    m = measurer or TextMeasurer()
    size = max_size
    budget = int(bbox.w * WRAP_SAFETY)
    while True:
        lines = m.wrap(spans, family, size, bbox.w, line_spacing)
        height = sum(ln.height_emu for ln in lines)
        line_cap_ok = max_lines is None or len(lines) <= max_lines
        # a kept-whole overlong token leaves an over-wide line: that is a fit
        # failure too — shrink until it fits, never mid-word split
        width_ok = all(ln.width_emu <= budget for ln in lines)
        if (height <= bbox.h and line_cap_ok and width_ok) \
                or strategy == "wrap_only":
            return FitResult(size, lines, False, height,
                             _spacing_pt(lines, size))
        if size - 0.5 >= min_size:
            size -= 0.5
            continue
        if strategy == "shrink_only":
            return FitResult(size, lines, False, height, _spacing_pt(lines, size))
        # at the size floor: ellipsize any still-overwide token in place
        ellipsized = False
        for ln in lines:
            if ln.width_emu > budget and ln.spans:
                head_w = sum(m.span_width_emu(s, family, size)
                             for s in ln.spans[:-1])
                ln.spans[-1] = m.ellipsize_token(
                    ln.spans[-1], family, size, budget - head_w)
                ln.width_emu = head_w + m.span_width_emu(
                    ln.spans[-1], family, size)
                ellipsized = True
        if height <= bbox.h and line_cap_ok:
            return FitResult(size, lines, ellipsized, height,
                             _spacing_pt(lines, size))
        # truncate: keep as many whole lines as fit, ellipsize the last
        kept: list[Line] = []
        used = 0
        for ln in lines:
            if used + ln.height_emu > bbox.h or (max_lines and len(kept) >= max_lines):
                break
            kept.append(ln)
            used += ln.height_emu
        if kept:
            last = kept[-1]
            if last.spans:
                last.spans[-1] = replace(
                    last.spans[-1],
                    text=last.spans[-1].text.rstrip().rstrip(".,;") + ELLIPSIS)
        return FitResult(size, kept, True, sum(l.height_emu for l in kept),
                         _spacing_pt(kept, size))


def _spacing_pt(lines: list[Line], size: float) -> float:
    if not lines:
        return size * 1.15
    return max(ln.height_emu for ln in lines) / EMU_PER_PT

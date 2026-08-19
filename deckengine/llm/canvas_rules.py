"""Deterministic design rails for canvas slides — the safety net that makes
freeform generation shippable.

Geometry sanity (bounds, slivers, count) already fails at Pydantic
validation; these rails catch the CONTENT-AWARE defects a first-draft
design makes — text colliding with text, dark-on-dark contrast, unreadable
sliver text — and phrase them as repair-loop problems in the house style.
Every rail offers a legal exit (the PlainStr lesson: never demand what the
schema cannot express).

Overlap semantics are z-aware: a label-less canvas_shape at LOWER z that
contains an element is a PANEL (the canonical design gesture, legal);
text-bearing elements intersecting each other is a defect.
"""
from __future__ import annotations

from ..schema.canvas import CanvasElement, CanvasSlideSpec

# fills dark enough that ink/ink_muted text on them is unreadable
_DARK_FILLS = frozenset({"primary", "primary_dark", "accent", "negative",
                         "positive", "ink"})
_DARK_TEXT = frozenset({"ink", "ink_muted", "primary", "primary_dark"})
_LIGHT_TEXT = frozenset({"inverse_ink"})  # unreadable on light fills/bg
_OVERLAP_FRAC = 0.10   # intersection / smaller area above this = collision
_CONTAIN_FRAC = 0.90   # inner mostly inside outer = containment
_SLIVER_W = 0.06       # text narrower than this will ellipsize hard


def _rect(el: CanvasElement) -> tuple[float, float, float, float]:
    return el.x, el.y, el.x + el.w, el.y + el.h


def _inter_frac(a: CanvasElement, b: CanvasElement) -> float:
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    iw = min(ax1, bx1) - max(ax0, bx0)
    ih = min(ay1, by1) - max(ay0, by0)
    if iw <= 0 or ih <= 0:
        return 0.0
    smaller = min(a.w * a.h, b.w * b.h)
    return (iw * ih) / smaller if smaller > 0 else 0.0


def _contained_in(inner: CanvasElement, outer: CanvasElement) -> bool:
    return _inter_frac(inner, outer) >= _CONTAIN_FRAC and \
        (inner.w * inner.h) <= (outer.w * outer.h)


# only flat rectangles read as backdrops; an arrow/chevron/oval crossing
# text reads as a collision, not a panel (seen live: text half-on/half-off
# giant chevron arrows)
_PANEL_SHAPES = frozenset({"rect", "rounded"})


def _is_panel(el: CanvasElement) -> bool:
    return (el.content.kind == "canvas_shape"
            and not (el.content.label or "").strip()
            and (el.content.shape or "rect") in _PANEL_SHAPES)


def _bears_text(el: CanvasElement) -> bool:
    k = el.content.kind
    if k == "canvas_text":
        return True
    if k == "canvas_shape":
        return bool((el.content.label or "").strip())
    return k != "canvas_line"   # every component leaf renders text


def _label(el: CanvasElement, i: int) -> str:
    k = el.content.kind
    if k == "canvas_text":
        return f"text element {i + 1} ({el.content.text[:28]!r})"
    if k == "canvas_shape":
        return f"shape element {i + 1}" + (
            f" ({el.content.label[:24]!r})" if el.content.label else "")
    return f"{k} element {i + 1}"


def check_canvas_slide(slide: CanvasSlideSpec) -> list[str]:
    """Design problems for one canvas slide (deterministic, free)."""
    problems: list[str] = []
    els = slide.elements

    # 1) text-on-text collision (panels at lower z exempt the contained)
    for i in range(len(els)):
        for j in range(i + 1, len(els)):
            a, b = els[i], els[j]
            if not (_bears_text(a) and _bears_text(b)):
                continue
            frac = _inter_frac(a, b)
            if frac <= _OVERLAP_FRAC:
                continue
            lo, hi = (a, b) if a.z <= b.z else (b, a)
            if _is_panel(lo) and _contained_in(hi, lo):
                continue  # classic panel-with-content
            problems.append(
                f"{_label(a, i)} overlaps {_label(b, j)} by "
                f"{frac:.0%}: move or resize one of them so text never "
                f"collides (or put the content INSIDE a label-less panel "
                f"shape at a lower z)")
            if len(problems) >= 4:   # one repair pass fixes geometry wholesale
                return problems

    # 2) contrast: dark text sitting on a dark panel beneath it
    for i, el in enumerate(els):
        role = None
        if el.content.kind == "canvas_text":
            role = el.content.color_role
        elif el.content.kind == "canvas_shape" and el.content.label:
            if (el.content.fill_role or "") in _DARK_FILLS \
                    and el.content.label_color_role in _DARK_TEXT:
                problems.append(
                    f"{_label(el, i)} has {el.content.label_color_role!r} "
                    f"label on a {el.content.fill_role!r} fill: set "
                    f"label_color_role='inverse_ink' or lighten the fill")
            elif (el.content.fill_role or "") not in _DARK_FILLS \
                    and el.content.label_color_role in _LIGHT_TEXT:
                problems.append(
                    f"{_label(el, i)} has {el.content.label_color_role!r} "
                    f"label on a light {el.content.fill_role!r} fill: set "
                    f"label_color_role='ink' or use a dark fill")
            continue
        if role in _LIGHT_TEXT:
            on_dark = slide.bg_fill_role in _DARK_FILLS or any(
                p.content.kind == "canvas_shape" and p is not el
                and p.z <= el.z
                and (p.content.fill_role or "") in _DARK_FILLS
                and _contained_in(el, p) for p in els)
            if not on_dark:
                problems.append(
                    f"{_label(el, i)} uses color_role={role!r} on a light "
                    f"background: set color_role='ink' or place it on a "
                    f"dark panel")
            continue
        if role not in _DARK_TEXT:
            continue
        for j, panel in enumerate(els):
            if panel is el or panel.content.kind != "canvas_shape":
                continue
            if panel.z <= el.z and (panel.content.fill_role or "") in \
                    _DARK_FILLS and _contained_in(el, panel):
                problems.append(
                    f"{_label(el, i)} uses color_role={role!r} on top of a "
                    f"{panel.content.fill_role!r} panel: set "
                    f"color_role='inverse_ink' (or move it off the panel)")
                break
    if slide.bg_fill_role in _DARK_FILLS:
        for i, el in enumerate(els):
            if el.content.kind == "canvas_text" \
                    and el.content.color_role in _DARK_TEXT \
                    and not any(p.content.kind == "canvas_shape"
                                and p.z <= el.z and _contained_in(el, p)
                                and (p.content.fill_role or "") not in
                                _DARK_FILLS for p in els):
                problems.append(
                    f"{_label(el, i)} uses color_role="
                    f"{el.content.color_role!r} on the dark "
                    f"bg_fill_role={slide.bg_fill_role!r}: use "
                    f"'inverse_ink' or place it on a light panel")
                break

    # 2b) components inside dark panels: component leaves render theme-ink
    # text on light surfaces by design, so a component contained in a dark
    # panel is unreadable (seen live: option columns inside a navy panel)
    for i, el in enumerate(els):
        if el.content.kind in ("canvas_text", "canvas_shape", "canvas_line"):
            continue
        for p in els:
            if p is el or p.content.kind != "canvas_shape":
                continue
            if p.z <= el.z and (p.content.fill_role or "") in _DARK_FILLS \
                    and _contained_in(el, p):
                problems.append(
                    f"{_label(el, i)} sits inside a dark "
                    f"{p.content.fill_role!r} panel: components render dark "
                    f"ink text and are unreadable on dark fills — move it "
                    f"off the panel or use a light panel fill like "
                    f"'surface'")
                break

    # 3) sliver text: a narrow column of long text ellipsizes to nothing
    for i, el in enumerate(els):
        if el.content.kind == "canvas_text" and el.w < _SLIVER_W \
                and len(el.content.text) > 12:
            problems.append(
                f"{_label(el, i)} is only {el.w:.0%} of the slide wide but "
                f"carries {len(el.content.text)} characters: widen it to "
                f">=0.12 or shorten the text")

    # 4) dead canvas: a design that uses less than half the surface reads
    # as an empty slide (seen live: content compressed into a middle band)
    coverage = sum(el.w * el.h for el in els)
    if coverage < 0.55:
        problems.append(
            f"the design covers only {coverage:.0%} of the canvas: enlarge "
            f"the dominant element, spread elements to the full height, or "
            f"add a supporting panel — no dead quadrants")

    # 5) fixed-height components crammed into boxes they cannot fit: they
    # overflow and paint over neighbours (seen live: a callout_band over a
    # chart). Floors are conservative fractions of the body height.
    for i, el in enumerate(els):
        floor = _MIN_H.get(el.content.kind)
        if floor and el.h < floor:
            problems.append(
                f"{el.content.kind} element {i + 1} has height {el.h:.2f} "
                f"but needs >= {floor:.2f} to render without overflowing "
                f"its box: make it taller, or use a canvas_shape/"
                f"canvas_text instead")

    return problems


# components with intrinsic minimum heights (body-height fractions);
# below these they overflow their cell instead of shrinking
_MIN_H = {
    "callout_band": 0.16, "kpi_card_strip": 0.18, "arrow_callout": 0.18,
    "icon_stat_row": 0.10, "icon_tile_row": 0.16, "funnel": 0.30,
    "comparison_columns": 0.35, "data_table": 0.30, "timeline_row": 0.16,
    "chevron_pathway": 0.10, "native_chart": 0.28, "matrix_2x2": 0.35,
    "brace_group": 0.25, "two_tone_header": 0.08,
}

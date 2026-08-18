"""canvas assembler — render a freeform-designed slide.

Every text element passes through fit_text INTO its box (overflow is
structurally impossible); component leaves render through the standard
Component contract with their element box as the cell; shapes/lines paint
by z-order. A light alignment pass snaps near-aligned edges (the hand-built
tell is crisp alignment, and the LLM's fractions are approximate).
"""
from __future__ import annotations

from dataclasses import replace

from ..components.base import RenderContext, get_component
from ..core.bbox import BBox
from ..core.fit_text import Span, fit_text
from ..core.pptx_shapes import add_hline, add_shape, add_vline
from ..core.pptx_text import add_text_box, make_text_frame, write_fit_result
from ..layout.zones import SLIDE
from ..schema.canvas import CanvasElement, CanvasSlideSpec
from ..schema.rich import parse_rich
from .base import SlideAssembler, register_slide

_SNAP_TOL = 0.02      # edges within this fraction snap to a shared line
_GRID_X = 24          # layout grid: 24 columns...
_GRID_Y = 16          # ...x 16 rows — the hand-built alignment discipline
_KICKER_SPC = 0.9     # letter-spacing for caps text (matches section_header)
_TEXT_MIN_FRAC = 0.5  # text may shrink to half its asked size before ellipsis


def _qpos(v: float, grid: int) -> float:
    """Positions always land on the nearest grid line."""
    return min(1.0, max(0.0, round(v * grid) / grid))


def _qsize(v: float, grid: int) -> float:
    """Sizes quantize too — except sub-cell sizes (thin rules) keep their
    exact extent."""
    return v if v < 1.0 / grid else round(v * grid) / grid


def _snap(elements: list[CanvasElement]) -> list[tuple[float, float, float, float]]:
    """Snapped (x, y, w, h) per element. Pass 1: edges within _SNAP_TOL of
    an earlier element's edge adopt it (mutual intent wins). Pass 2: the
    result quantizes to the 24x16 layout grid, so freehand fractions land
    on shared lines. Order matters — quantizing first can split a
    near-pair across a cell boundary. Pure function: rails and render see
    the same geometry."""
    out: list[list[float]] = []
    for el in elements:
        x, y, w, h = el.x, el.y, el.w, el.h
        r, b = x + w, y + h
        for px, py, pw, ph in out:
            pr, pb = px + pw, py + ph
            for cand in (px, pr):
                if abs(x - cand) <= _SNAP_TOL:
                    r0 = x + w
                    x = cand
                    w = max(0.02, r0 - x)
                if abs(r - cand) <= _SNAP_TOL:
                    w = max(0.02, cand - x)
                    r = x + w
            for cand in (py, pb):
                if abs(y - cand) <= _SNAP_TOL:
                    b0 = y + h
                    y = cand
                    h = max(0.015, b0 - y)
                if abs(b - cand) <= _SNAP_TOL:
                    h = max(0.015, cand - y)
                    b = y + h
        out.append([x, y, w, h])
    # pass 2 quantizes EDGES (not sizes): two elements sharing an edge —
    # including one's bottom against another's top — keep sharing it after
    # quantization. Sub-cell extents (thin rules) keep their exact size.
    snapped = []
    for x, y, w, h in out:
        qx0 = _qpos(x, _GRID_X)
        qx1 = (qx0 + w) if w < 1.0 / _GRID_X else _qpos(x + w, _GRID_X)
        qy0 = _qpos(y, _GRID_Y)
        qy1 = (qy0 + h) if h < 1.0 / _GRID_Y else _qpos(y + h, _GRID_Y)
        qw = max(0.02, min(qx1 - qx0, 1.0 - qx0))
        qh = max(0.015, min(qy1 - qy0, 1.0 - qy0))
        snapped.append((qx0, qy0, qw, qh))
    return snapped


@register_slide("canvas")
class CanvasSlide(SlideAssembler):
    def assemble(self, slide, spec: CanvasSlideSpec,
                 ctx: RenderContext) -> None:
        theme = ctx.theme
        if spec.bg_fill_role:
            add_shape(slide, SLIDE, theme, shape="rect",
                      fill_role=spec.bg_fill_role)
        if spec.render_title:
            z = self.render_title(slide, spec, ctx)
            area = z["body"]
        else:
            area = SLIDE

        # the footnote strip is RESERVED before any element is placed: the
        # fill rail pushes designs to the full body height, so a footnote
        # painted over the bottom row was a guaranteed overlap class
        fn = fh = None
        if spec.footnote:
            from ..schema.components import TextBlockSpec
            fn = TextBlockSpec(text=spec.footnote, size_role="micro",
                               color_role="ink_muted")
            fh = get_component("text_block").measure(fn, area.w, ctx)
            elem_area = BBox(area.x, area.y, area.w,
                             max(1, area.h - fh - theme.spacing(0.4)))
        else:
            elem_area = area

        geoms = _snap(spec.elements)
        geoms = self._grow_starved(spec.elements, geoms, elem_area, ctx)
        order = sorted(range(len(spec.elements)),
                       key=lambda i: (spec.elements[i].z, i))
        for i in order:
            el = spec.elements[i]
            x, y, w, h = geoms[i]
            box = BBox(elem_area.x + round(x * elem_area.w),
                       elem_area.y + round(y * elem_area.h),
                       max(1, round(w * elem_area.w)),
                       max(1, round(h * elem_area.h)))
            self._render_element(slide, el, box, ctx)

        if fn is not None:
            get_component("text_block").render(
                slide, fn, BBox(area.x, area.bottom - fh, area.w, fh), ctx)

    # -- geometry relief ----------------------------------------------------

    @staticmethod
    def _grow_starved(elements, geoms, area, ctx):
        """Deterministic overflow relief: a COMPONENT needing more height
        than its box grows downward into FREE canvas (no other element in
        its x-span below it), capped at the body bottom. Kills the
        'needs 1.24in but box is 1.00in' class with zero LLM calls; the
        pre-measure warning still fires for whatever growth can't cover.
        Text/shape/line elements are untouched — text fits itself."""
        out = [tuple(g) for g in geoms]
        for i, el in enumerate(elements):
            if el.content.kind in ("canvas_text", "canvas_shape",
                                   "canvas_line"):
                continue
            x, y, w, h = out[i]
            try:
                comp = get_component(el.content.kind)
                natural = comp.measure(el.content,
                                       max(1, round(w * area.w)), ctx)
            except Exception:  # noqa: BLE001 — measuring must never block
                continue
            need = natural / area.h
            if need <= h * 1.02:
                continue
            bottom = y + h
            limit = 1.0
            for j, (ox, oy, ow, oh) in enumerate(out):
                if j != i and ox < x + w and ox + ow > x \
                        and oy >= bottom - 1e-6:
                    limit = min(limit, oy - 0.01)   # keep a hairline gap
            grown = min(need, limit - y)
            if grown > h:
                out[i] = (x, y, w, grown)
        return out

    # -- element dispatch ---------------------------------------------------

    def _render_element(self, slide, el: CanvasElement, box: BBox,
                        ctx: RenderContext) -> None:
        c = el.content
        kind = c.kind
        if kind == "canvas_text":
            self._text(slide, c, box, ctx)
        elif kind == "canvas_shape":
            self._shape(slide, c, box, ctx)
        elif kind == "canvas_line":
            if c.direction == "h":
                add_hline(slide, box.x, box.y + box.h // 2, box.w, ctx.theme,
                          role=c.role, weight_pt=c.weight_pt, dash=c.dash)
            else:
                add_vline(slide, box.x + box.w // 2, box.y, box.h, ctx.theme,
                          role=c.role, weight_pt=c.weight_pt, dash=c.dash)
        else:  # any registered component: box is its cell, flexers may fill
            comp = get_component(kind)
            try:  # pre-measure: a starved box is a DENSITY defect (content
                natural = comp.measure(c, box.w, ctx)   # compresses/truncates)
                if natural > box.h * 1.10:
                    # most components FIT into their box (the engine's core
                    # promise); the few that truly paint beyond it report
                    # 'exceeds bbox'/'taller than provided bbox' themselves,
                    # and the render audit catches any actual collision —
                    # those are the repairable overlap signals, not this
                    from ..core.units import to_inch
                    ctx.report.warn(
                        f"canvas: {kind} tight in its box (needs "
                        f"{to_inch(natural):.2f}in, has {to_inch(box.h):.2f}"
                        f"in) — content compresses or truncates")
            except Exception:  # noqa: BLE001 — measuring must never block
                pass
            ctx.fill_hint = True
            try:
                comp.render(slide, c, box, ctx)
            finally:
                ctx.fill_hint = False

    def _text(self, slide, c, box: BBox, ctx: RenderContext) -> None:
        size = c.size_pt if c.size_pt is not None else ctx.size(c.size_role)
        spans = parse_rich(c.text, base_color_role=c.color_role)
        if c.caps:
            spans = [replace(s, caps=True, spc_pts=_KICKER_SPC)
                     for s in spans]
        family = ctx.font("display") if c.font == "display" \
            else ctx.font("body")
        fit = fit_text(spans, BBox(0, 0, box.w, box.h), family,
                       max_size=size,
                       min_size=max(6.5, size * _TEXT_MIN_FRAC),
                       measurer=ctx.measurer)
        if fit.truncated:
            ctx.report.truncated(f"canvas text: {c.text[:40]!r}")
        tb = add_text_box(slide, box, align=c.align, anchor=c.anchor)
        write_fit_result(tb.text_frame, fit, ctx.theme, family=family,
                         align=c.align, default_color_role=c.color_role)

    def _shape(self, slide, c, box: BBox, ctx: RenderContext) -> None:
        s = add_shape(slide, box, ctx.theme, shape=c.shape,
                      fill_role=c.fill_role, line_role=c.line_role,
                      line_w_pt=c.line_w_pt, corner_radius=c.corner_radius,
                      shadow=c.shadow)
        if not (c.label or "").strip():
            return
        pad = ctx.theme.spacing(0.4)
        fit = fit_text(parse_rich(c.label,
                                  base_color_role=c.label_color_role),
                       BBox(0, 0, max(1, box.w - 2 * pad),
                            max(1, box.h - ctx.theme.spacing(0.3))),
                       ctx.font("body"),
                       max_size=ctx.size(c.label_size_role), min_size=6.5,
                       measurer=ctx.measurer)
        if fit.truncated:
            ctx.report.truncated(f"canvas shape label: {c.label[:40]!r}")
        tf = make_text_frame(s, align="center", anchor="middle")
        write_fit_result(tf, fit, ctx.theme, family=ctx.font("body"),
                         align="center",
                         default_color_role=c.label_color_role)

"""tree — issue tree / driver tree / org chart (canon gaps closed).

The MECE decomposition form: a root split into 2-4 branches, each with up
to 3 leaf lines. 'issue'/'driver' lay out LEFT->RIGHT (root box middle-
left, elbow connectors to branch boxes, leaves as text lines under each
branch); 'driver' adds a micro operator chip (+ or x) on each connector —
the KPI-math tree. 'org' lays TOP-DOWN (root top-center).

measure(): branch-column arithmetic (branch box fit + leaf lines) shared
with render() via _plan — parity by construction.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.bbox import BBox
from ..core.fit_text import FitResult, Span, fit_text
from ..core.pptx_shapes import add_line, add_shape
from ..core.pptx_text import add_text_box, make_text_frame, \
    write_fit_result, write_spans_paragraph
from ..core.units import inch, to_inch, to_pt
from ..schema.components import TreeSpec
from ..schema.rich import parse_rich
from .base import Component, RenderContext, register

_ROOT_W_FRAC = 0.24        # issue/driver: root box width share
_BRANCH_PAD = 0.35         # box inner padding (spacing multiples)
_GAP_MULT = 0.7            # vertical gap between branch blocks
_MIN_LABEL = 7.0
_PROBE_H = 10_000_000
_CHIP_D = inch(0.26)       # operator chip diameter


@dataclass(frozen=True)
class _Branch:
    fit: FitResult
    leaf_fits: tuple[FitResult, ...]
    block_h: int               # box + leaves + inner gaps


@dataclass(frozen=True)
class _Plan:
    root_fit: FitResult
    branches: tuple[_Branch, ...]
    box_h: int                 # uniform branch-box height
    total: int


@register("tree")
class Tree(Component):
    spec_model = TreeSpec

    def _plan(self, data: TreeSpec, width: int,
              ctx: RenderContext) -> _Plan:
        theme = ctx.theme
        family = ctx.font("body")
        pad = theme.spacing(_BRANCH_PAD)
        horizontal = data.variant != "org"
        n = len(data.children)
        if horizontal:
            root_w = round(width * _ROOT_W_FRAC)
            branch_w = width - root_w - theme.spacing(2.2)
        else:
            branch_w = (width - (n - 1) * theme.spacing(0.5)) // n
            root_w = min(round(width * 0.4), branch_w * 2)
        root_fit = fit_text(
            [Span(s.text, bold=True, italic=s.italic,
                  color_role="inverse_ink")
             for s in parse_rich(data.root, base_color_role="inverse_ink")],
            BBox(0, 0, max(1, root_w - 2 * pad), _PROBE_H), family,
            max_size=ctx.size("small"), min_size=_MIN_LABEL, max_lines=3,
            measurer=ctx.measurer)

        branches: list[_Branch] = []
        box_h = 0
        for ch in data.children:
            bfit = fit_text(
                [Span(s.text, bold=True, italic=s.italic, color_role="ink")
                 for s in parse_rich(ch.label, base_color_role="ink")],
                BBox(0, 0, max(1, branch_w - 2 * pad), _PROBE_H), family,
                max_size=ctx.size("small"), min_size=_MIN_LABEL,
                max_lines=2, measurer=ctx.measurer)
            leaf_fits = tuple(
                fit_text([Span(leaf, color_role="ink_muted")],
                         BBox(0, 0, max(1, branch_w - 2 * pad
                                        - theme.spacing(0.8)), _PROBE_H),
                         family, max_size=ctx.size("micro"),
                         min_size=6.5, max_lines=1,
                         measurer=ctx.measurer)
                for leaf in ch.children)
            branches.append(_Branch(bfit, leaf_fits, 0))
            box_h = max(box_h, bfit.height_emu + 2 * pad)

        done: list[_Branch] = []
        for b in branches:
            leaves_h = sum(f.height_emu for f in b.leaf_fits)
            leaves_h += theme.spacing(0.25) * len(b.leaf_fits)
            done.append(_Branch(b.fit, b.leaf_fits, box_h + leaves_h))

        gap = theme.spacing(_GAP_MULT)
        if horizontal:
            total = sum(b.block_h for b in done) + (n - 1) * gap
            total = max(total, root_fit.height_emu + 2 * pad)
        else:
            root_h = root_fit.height_emu + 2 * pad
            total = root_h + theme.spacing(1.2) + \
                max(b.block_h for b in done)
        return _Plan(root_fit, tuple(done), box_h, total)

    def measure(self, data: TreeSpec, width: int,
                ctx: RenderContext) -> int:
        return self._plan(data, width, ctx).total

    def render(self, slide, data: TreeSpec, bbox: BBox,
               ctx: RenderContext) -> int:
        theme = ctx.theme
        plan = self._plan(data, bbox.w, ctx)
        if plan.total > bbox.h:
            ctx.report.warn(
                f"tree: needs {to_inch(plan.total):.2f}in but bbox is "
                f"{to_inch(bbox.h):.2f}in; rendering anyway (may clip)")
        n = len(data.children)
        hi = data.highlight_index
        if hi is not None and not 0 <= hi < n:
            ctx.report.warn(f"tree: highlight_index {hi} out of range for "
                            f"{n} branches; ignoring")
            hi = None
        if data.variant == "org":
            return self._render_org(slide, data, bbox, plan, hi, ctx)
        return self._render_horizontal(slide, data, bbox, plan, hi, ctx)

    # -- issue / driver: left -> right ------------------------------------

    def _render_horizontal(self, slide, data: TreeSpec, bbox: BBox,
                           plan: _Plan, hi, ctx) -> int:
        theme = ctx.theme
        family = ctx.font("body")
        pad = theme.spacing(_BRANCH_PAD)
        gap = theme.spacing(_GAP_MULT)
        root_w = round(bbox.w * _ROOT_W_FRAC)
        branch_x = bbox.x + root_w + theme.spacing(2.2)
        branch_w = bbox.right - branch_x

        # root box, vertically centered on the block stack
        root_h = plan.root_fit.height_emu + 2 * pad
        root_y = bbox.y + (plan.total - root_h) // 2
        root = BBox(bbox.x, root_y, root_w, root_h)
        rs = add_shape(slide, root, theme, shape="rounded",
                       fill_role="primary_dark", corner_radius=0.12)
        tf = make_text_frame(rs, align="center", anchor="middle")
        write_fit_result(tf, plan.root_fit, theme, family=family,
                         align="center", default_color_role="inverse_ink")

        trunk_x = bbox.x + root_w + theme.spacing(1.1)
        y = bbox.y
        first_mid = last_mid = None
        for i, (ch, b) in enumerate(zip(data.children, plan.branches)):
            box = BBox(branch_x, y, branch_w, plan.box_h)
            mid_y = box.y + plan.box_h // 2
            first_mid = mid_y if first_mid is None else first_mid
            last_mid = mid_y
            fill = "accent" if i == hi else "surface_alt"
            ink = "inverse_ink" if i == hi else "ink"
            bs = add_shape(slide, box, theme, shape="rounded",
                           fill_role=fill, corner_radius=0.12,
                           line_role="grid", line_w_pt=0.75)
            btf = make_text_frame(bs, align="left", anchor="middle")
            btf.margin_left = pad
            btf.margin_right = pad
            write_fit_result(btf, b.fit, theme, family=family,
                             default_color_role=ink)
            # elbow: trunk vertical handles the fan; here the horizontal leg
            add_line(slide, trunk_x, mid_y, branch_x, mid_y, theme,
                     role="grid", weight_pt=1.0)
            if data.variant == "driver":
                chip = BBox(trunk_x + (branch_x - trunk_x) // 2
                            - _CHIP_D // 2, mid_y - _CHIP_D // 2,
                            _CHIP_D, _CHIP_D)
                cs = add_shape(slide, chip, theme, shape="oval",
                               fill_role="primary")
                ctf = make_text_frame(cs, align="center", anchor="middle")
                write_spans_paragraph(
                    ctf, [Span("×" if data.operator == "x" else "+",
                               bold=True, color_role="inverse_ink")],
                    ctx.size("micro"), theme, family=family, align="center",
                    default_color_role="inverse_ink")
            # leaves under the box
            ly = box.bottom + theme.spacing(0.25)
            for lf in b.leaf_fits:
                lbox = add_text_box(
                    slide, BBox(branch_x + theme.spacing(0.8), ly,
                                max(1, branch_w - theme.spacing(0.8)),
                                lf.height_emu))
                write_fit_result(lbox.text_frame, lf, theme, family=family,
                                 default_color_role="ink_muted")
                ly += lf.height_emu + theme.spacing(0.25)
            y += b.block_h + gap
        # trunk vertical + stub from the root
        add_line(slide, root.right, root_y + root_h // 2, trunk_x,
                 root_y + root_h // 2, theme, role="grid", weight_pt=1.0)
        add_line(slide, trunk_x, first_mid, trunk_x, last_mid, theme,
                 role="grid", weight_pt=1.0)
        return plan.total

    # -- org: top -> down ---------------------------------------------------

    def _render_org(self, slide, data: TreeSpec, bbox: BBox,
                    plan: _Plan, hi, ctx) -> int:
        theme = ctx.theme
        family = ctx.font("body")
        pad = theme.spacing(_BRANCH_PAD)
        n = len(data.children)
        col_gap = theme.spacing(0.5)
        col_w = (bbox.w - (n - 1) * col_gap) // n
        root_w = min(round(bbox.w * 0.4), col_w * 2)
        root_h = plan.root_fit.height_emu + 2 * pad
        root = BBox(bbox.x + (bbox.w - root_w) // 2, bbox.y, root_w, root_h)
        rs = add_shape(slide, root, theme, shape="rounded",
                       fill_role="primary_dark", corner_radius=0.12)
        tf = make_text_frame(rs, align="center", anchor="middle")
        write_fit_result(tf, plan.root_fit, theme, family=family,
                         align="center", default_color_role="inverse_ink")

        rail_y = root.bottom + theme.spacing(0.6)
        boxes_y = bbox.y + root_h + theme.spacing(1.2)
        add_line(slide, root.x + root_w // 2, root.bottom,
                 root.x + root_w // 2, rail_y, theme, role="grid",
                 weight_pt=1.0)
        first_cx = last_cx = None
        for i, (ch, b) in enumerate(zip(data.children, plan.branches)):
            x = bbox.x + i * (col_w + col_gap)
            cx = x + col_w // 2
            first_cx = cx if first_cx is None else first_cx
            last_cx = cx
            add_line(slide, cx, rail_y, cx, boxes_y, theme, role="grid",
                     weight_pt=1.0)
            fill = "accent" if i == hi else "surface_alt"
            ink = "inverse_ink" if i == hi else "ink"
            box = BBox(x, boxes_y, col_w, plan.box_h)
            bs = add_shape(slide, box, theme, shape="rounded",
                           fill_role=fill, corner_radius=0.12,
                           line_role="grid", line_w_pt=0.75)
            btf = make_text_frame(bs, align="center", anchor="middle")
            btf.margin_left = pad
            btf.margin_right = pad
            write_fit_result(btf, b.fit, theme, family=family,
                             align="center", default_color_role=ink)
            ly = box.bottom + theme.spacing(0.25)
            for lf in b.leaf_fits:
                lbox = add_text_box(
                    slide, BBox(x + theme.spacing(0.4), ly,
                                max(1, col_w - theme.spacing(0.8)),
                                lf.height_emu), align="center")
                write_fit_result(lbox.text_frame, lf, theme, family=family,
                                 align="center",
                                 default_color_role="ink_muted")
                ly += lf.height_emu + theme.spacing(0.25)
        add_line(slide, first_cx, rail_y, last_cx, rail_y, theme,
                 role="grid", weight_pt=1.0)
        return plan.total

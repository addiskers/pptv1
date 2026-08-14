"""Recursive layout tree — the compositional escape hatch (Q2).

custom_layout slides are composed per-content instead of stamped from a mold:
`rows`/`cols` split space, `panel` decorates, and ANY registered component is
a leaf. Nodes are themselves registered components, so trees nest freely and
keep the measure/render contract everywhere.

Deterministic rails live here so a bad tree fails Pydantic validation and
feeds the existing LLM repair loop for free:
- depth <= MAX_DEPTH, leaves <= MAX_LEAVES
- fracs: one per child, none below MIN_FRAC (no slivers), sum ~ 1.0
- the root must be a rows/cols node (a single leaf means a standard
  archetype should have been used instead)
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

from .components import ComponentSpec

MAX_DEPTH = 4
MAX_LEAVES = 14
MIN_FRAC = 0.08
_FRAC_SUM_TOL = 0.05


def _check_fracs(fracs: list[float] | None, n_children: int) -> None:
    if fracs is None:
        return
    if len(fracs) != n_children:
        raise ValueError(
            f"fracs has {len(fracs)} entries for {n_children} children")
    if min(fracs) < MIN_FRAC:
        raise ValueError(
            f"frac {min(fracs)} below {MIN_FRAC} — sliver cells are unreadable")
    if abs(sum(fracs) - 1.0) > _FRAC_SUM_TOL:
        raise ValueError(f"fracs sum to {sum(fracs):.2f}, expected ~1.0")


class RowsNode(BaseModel):
    """Vertical split. fracs give each child a height share of the assigned
    zone (bespoke fill mode); without fracs children stack at natural height.
    pin_last anchors the final child to the zone bottom when there is
    surplus (owner bands, source rows) — the hand-built gesture."""
    kind: Literal["rows"] = "rows"
    children: list[LayoutChild] = Field(min_length=2, max_length=6)
    fracs: list[float] | None = None
    gap: float = Field(default=0.8, ge=0, le=4)  # spacing multiples
    pin_last: bool = False

    @model_validator(mode="after")
    def _fracs_sane(self):
        _check_fracs(self.fracs, len(self.children))
        return self


class ColsNode(BaseModel):
    """Horizontal split on one shared track (equal heights, like
    comparison_columns). fracs give width shares; without fracs, equal."""
    kind: Literal["cols"] = "cols"
    children: list[LayoutChild] = Field(min_length=2, max_length=4)
    fracs: list[float] | None = None
    gap: float = Field(default=0.4, ge=0, le=4)
    align: Literal["top", "middle"] = "top"

    @model_validator(mode="after")
    def _fracs_sane(self):
        _check_fracs(self.fracs, len(self.children))
        return self


class PanelNode(BaseModel):
    """Decorated wrapper: background/border/rounded/shadow + inset, then
    delegate to the single child."""
    kind: Literal["panel"] = "panel"
    child: LayoutChild
    fill_role: str | None = None
    border_role: str | None = None
    rounded: bool = False
    shadow: bool = False
    inset: float = Field(default=0.6, ge=0, le=4)  # spacing multiples


LayoutChild = Annotated[
    Union[RowsNode, ColsNode, PanelNode, ComponentSpec],
    Field(discriminator="kind"),
]

RowsNode.model_rebuild()
ColsNode.model_rebuild()
PanelNode.model_rebuild()

_NODE_TYPES = (RowsNode, ColsNode, PanelNode)


def tree_stats(node) -> tuple[int, int]:
    """(depth, leaf_count) — leaves are ordinary component specs. panel is
    decoration, not a split: it does not consume a depth level (otherwise the
    canonical 2x2 matrix-of-panels would be illegal)."""
    if isinstance(node, PanelNode):
        return tree_stats(node.child)
    if isinstance(node, (RowsNode, ColsNode)):
        stats = [tree_stats(c) for c in node.children]
        return 1 + max(d for d, _ in stats), sum(n for _, n in stats)
    return 1, 1


def _leaf_kinds(node) -> list[str]:
    if isinstance(node, PanelNode):
        return _leaf_kinds(node.child)
    if isinstance(node, (RowsNode, ColsNode)):
        return [k for c in node.children for k in _leaf_kinds(c)]
    return [getattr(node, "kind", "")]


def check_tree(root) -> list[str]:
    """Whole-tree rails (per-node frac sanity is enforced on the nodes)."""
    problems = []
    if not isinstance(root, (RowsNode, ColsNode)):
        problems.append(
            "root must be a rows or cols node — a single component means a "
            "standard archetype fits, use that instead")
        return problems
    depth, leaves = tree_stats(root)
    if depth > MAX_DEPTH:
        problems.append(f"tree depth {depth} exceeds {MAX_DEPTH}")
    if leaves > MAX_LEAVES:
        problems.append(f"{leaves} leaves exceed {MAX_LEAVES} — merge cells")
    if "section_header" in _leaf_kinds(root):
        problems.append(
            "custom_layout must not embed section_header — the slide already "
            "has a title/subtitle; use a text_block with size_role 'h2' for "
            "an in-body heading")
    return problems

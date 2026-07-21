"""Rails: bad trees must fail Pydantic validation (feeding the repair loop);
good trees must pass."""
import pytest
from pydantic import ValidationError

from deckengine.schema.components import TextBlockSpec
from deckengine.schema.layout_tree import (ColsNode, PanelNode, RowsNode,
                                           check_tree, tree_stats)
from deckengine.schema.slide_types import CustomLayoutSpec


def leaf(text="x"):
    return TextBlockSpec(text=text)


def test_valid_tree_passes():
    spec = CustomLayoutSpec(
        title="A bespoke composition that proves the claim in one view",
        root=RowsNode(fracs=[0.7, 0.3], children=[
            ColsNode(children=[leaf("a"), leaf("b")]),
            PanelNode(fill_role="surface", child=ColsNode(
                children=[leaf("c"), leaf("d"), leaf("e")])),
        ]))
    depth, leaves = tree_stats(spec.root)
    assert depth == 4  # rows -> panel -> cols -> leaf
    assert leaves == 5


def test_leaf_root_rejected():
    with pytest.raises(ValidationError, match="root must be"):
        CustomLayoutSpec(title="t", root=leaf())


def test_sliver_frac_rejected():
    with pytest.raises(ValidationError, match="sliver"):
        RowsNode(fracs=[0.95, 0.05], children=[leaf(), leaf()])


def test_frac_count_mismatch_rejected():
    with pytest.raises(ValidationError, match="entries for"):
        ColsNode(fracs=[0.5, 0.3, 0.2], children=[leaf(), leaf()])


def test_frac_sum_off_rejected():
    with pytest.raises(ValidationError, match="sum"):
        RowsNode(fracs=[0.5, 0.3], children=[leaf(), leaf()])


def test_depth_rail():
    deep = RowsNode(children=[
        ColsNode(children=[
            RowsNode(children=[
                ColsNode(children=[leaf(), leaf()]),
                leaf()]),
            leaf()]),
        leaf()])
    assert tree_stats(deep)[0] == 5
    problems = check_tree(deep)
    assert any("depth" in p for p in problems)
    with pytest.raises(ValidationError, match="depth"):
        CustomLayoutSpec(title="t", root=deep)


def test_leaves_rail():
    wide = RowsNode(children=[
        ColsNode(children=[leaf(), leaf(), leaf(), leaf()]),
        ColsNode(children=[leaf(), leaf(), leaf(), leaf()]),
        ColsNode(children=[leaf(), leaf(), leaf(), leaf()]),
        ColsNode(children=[leaf(), leaf(), leaf(), leaf()]),
    ])
    assert tree_stats(wide)[1] == 16
    problems = check_tree(wide)
    assert any("leaves" in p for p in problems)


def test_heavyweight_component_is_one_leaf():
    from deckengine.schema.components import (ComparisonColumnSpec,
                                              ComparisonColumnsSpec,
                                              StatRowSpec, StatSpec)
    grid = ComparisonColumnsSpec(columns=[
        ComparisonColumnSpec(header="A", cells=[
            StatRowSpec(stats=[StatSpec(label="l", value="1")])]),
        ComparisonColumnSpec(header="B", cells=[
            StatRowSpec(stats=[StatSpec(label="l", value="2")])]),
    ])
    root = RowsNode(children=[grid, leaf()])
    assert tree_stats(root) == (2, 2)
    assert check_tree(root) == []

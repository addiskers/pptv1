"""The consulting-frameworks registry (dummy, not yet wired): every entry
well-formed, the menu complete, the selection prompt carries the doctrine."""
from deckengine.llm.frameworks import (FRAMEWORKS, SELECTION_PROMPT,
                                       framework_menu)


def test_registry_covers_the_canon():
    assert len(FRAMEWORKS) >= 10
    for must in ("bcg_matrix", "ansoff_matrix", "porters_five_forces",
                 "swot", "mckinsey_7s", "value_chain", "pestle",
                 "ge_mckinsey_nine_box", "three_cs", "issue_tree"):
        assert must in FRAMEWORKS, must


def test_entries_well_formed():
    for f in FRAMEWORKS.values():
        assert f.question.strip() and f.choose_when.strip()
        assert f.render_as.strip()
        assert f.cells, f.id                     # every framework names its parts
        if "matrix" in f.render_as:
            assert f.axes, f.id                  # matrices declare their axes


def test_menu_and_prompt():
    menu = framework_menu()
    assert all(fid in menu for fid in FRAMEWORKS)
    assert "bcg_matrix" in SELECTION_PROMPT
    # the doctrine: decision-driven, verdict-bearing, never decoration
    assert "decision" in SELECTION_PROMPT
    assert "VERDICT" in SELECTION_PROMPT

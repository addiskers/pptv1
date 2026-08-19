"""The consulting-frameworks registry: every entry well-formed, the
decision vocabulary exact, and no framework-name menu anywhere (the
naive menu is the path that mode-collapsed to BCG)."""
import deckengine.llm.frameworks as fw_mod
from deckengine.llm.frameworks import DECISION_TYPES, FRAMEWORKS, decision_menu

_KNOWN_SIGNALS = {"per_unit_share", "per_unit_growth", "many_units",
                  "multi_criteria"}


def test_registry_covers_the_canon():
    assert len(FRAMEWORKS) >= 10
    for must in ("bcg_matrix", "ansoff_matrix", "porters_five_forces",
                 "swot", "mckinsey_7s", "value_chain", "pestle",
                 "ge_mckinsey_nine_box", "three_cs", "issue_tree"):
        assert must in FRAMEWORKS, must


def test_entries_well_formed():
    for f in FRAMEWORKS.values():
        assert f.question.strip() and f.choose_when.strip()
        assert f.label.strip(), f.id
        assert f.render_as.strip()
        assert f.cells, f.id                     # every framework names its parts
        assert f.verdict_signal.strip(), f.id    # the verdict critic key
        if "matrix" in f.render_as:
            assert f.axes, f.id                  # matrices declare their axes
        for sig in f.requires:
            assert sig in _KNOWN_SIGNALS, (f.id, sig)


def test_decision_vocabulary_exact():
    assert set(DECISION_TYPES) == {
        "portfolio_allocation", "market_attractiveness", "growth_path",
        "positioning", "org_execution", "cost_structure", "macro_risk",
        "problem_structuring", "category_creation", "stocktake", "none"}
    for d in DECISION_TYPES.values():
        assert len(d.candidates) <= 2, d.id
        for c in d.candidates:
            assert c in FRAMEWORKS, (d.id, c)
    assert DECISION_TYPES["none"].candidates == ()


def test_tie_pairs_carry_avoid_criteria():
    # every decision type with 2 candidates needs discriminating
    # negative criteria — positive-only criteria cannot discriminate
    for d in DECISION_TYPES.values():
        if len(d.candidates) == 2:
            for c in d.candidates:
                assert FRAMEWORKS[c].avoid_when.strip(), (d.id, c)


def test_decision_menu_never_names_frameworks():
    menu = decision_menu().lower()
    for fid, f in FRAMEWORKS.items():
        assert fid not in menu, fid
        assert f.label.lower() not in menu, fid
    assert "bcg" not in menu and "porter" not in menu
    # 'none' is a schema value, not a menu entry
    assert "- none:" not in menu


def test_naive_menu_is_gone():
    # the mode-collapsing "pick a framework from a menu" path must not
    # come back under its old names
    assert not hasattr(fw_mod, "framework_menu")
    assert not hasattr(fw_mod, "SELECTION_PROMPT")

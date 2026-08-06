"""Engine-side style-priors loader tests — file + env driven, no LLM.

Every test repoints PRIORS_PATH at a tmp file and clears the
load_priors cache (autouse fixture) so tests stay order-independent.
"""
import json

import pytest

from deckengine.llm import style_priors

PRIORS = {
    "version": 1,
    "by_claim_context": {
        "ranking_comparison": {
            "n": 40,
            # waterfall outranks bar but is NOT renderable: it must
            # never be cited, nor endpoint_labels below
            "chart_type_freq": {"bar": 0.72, "waterfall": 0.95},
            "top_features": {"value_labels": 0.66,
                             "endpoint_labels": 0.9},
            # photo_background outranks so_what_band but is NOT
            # renderable craft: it must never be cited either
            "craft_freq": {"so_what_band": 0.44,
                           "photo_background": 0.99},
        },
        "growth": {
            "n": 30,
            "chart_type_freq": {"line": 0.8},
            "top_features": {"annotations": 0.5, "value_labels": 0.4,
                             "series_highlight": 0.35,
                             "sorted_desc": 0.3},
            "craft_freq": {"big_number": 0.25, "kpi_cards": 0.22},
        },
    },
    "global": {"density_mean": 0.4, "title_is_action_rate": 0.8,
               "craft_freq": {"so_what_band": 0.5}},
}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("DECKENGINE_STYLE_PRIORS", raising=False)
    style_priors.load_priors.cache_clear()
    yield
    style_priors.load_priors.cache_clear()


@pytest.fixture
def priors_file(tmp_path, monkeypatch):
    path = tmp_path / "style_priors.json"
    path.write_text(json.dumps(PRIORS), encoding="utf-8")
    monkeypatch.setattr(style_priors, "PRIORS_PATH", path)
    return path


def test_missing_file_yields_empty_block(tmp_path, monkeypatch):
    monkeypatch.setattr(style_priors, "PRIORS_PATH",
                        tmp_path / "nope.json")
    assert style_priors.load_priors() == {}
    assert style_priors.prior_block("chart_slide", "Acme leads") == ""


def test_invalid_json_yields_empty(tmp_path, monkeypatch):
    bad = tmp_path / "style_priors.json"
    bad.write_text('{"version": 1, "torn', encoding="utf-8")
    monkeypatch.setattr(style_priors, "PRIORS_PATH", bad)
    assert style_priors.load_priors() == {}
    assert style_priors.prior_block("chart_slide", "Acme leads") == ""


def test_non_dict_json_yields_empty(tmp_path, monkeypatch):
    arr = tmp_path / "style_priors.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(style_priors, "PRIORS_PATH", arr)
    assert style_priors.load_priors() == {}


def test_kill_switch_wins_even_with_valid_file(priors_file, monkeypatch):
    monkeypatch.setenv("DECKENGINE_STYLE_PRIORS", "0")
    assert style_priors.load_priors() == {}
    assert style_priors.prior_block("chart_slide", "Acme leads") == ""


def test_kill_switch_beats_a_warm_cache(priors_file, monkeypatch):
    assert style_priors.prior_block("chart_slide", "Acme leads") != ""
    monkeypatch.setenv("DECKENGINE_STYLE_PRIORS", "0")
    # cache is warm; the block must still honor the switch
    assert style_priors.prior_block("chart_slide", "Acme leads") == ""


def test_ranking_claim_cites_ranking_stats(priors_file):
    block = style_priors.prior_block(
        "chart_slide",
        "Acme leads the market; the top three players hold most of it")
    assert block.startswith("STYLE PRIORS")
    assert "ranking_comparison" in block
    assert "bar charts 72%" in block
    assert "value_labels on 66%" in block
    assert "so_what_band" in block
    # capability-gap names must never leak into a prompt
    assert "waterfall" not in block
    assert "endpoint_labels" not in block
    assert "photo_background" not in block


def test_growth_claim_routes_to_growth_bucket(priors_file):
    block = style_priors.prior_block(
        "custom_layout", "Revenue grew 12% annually across the region")
    assert "for growth claims" in block
    assert "line charts 80%" in block


def test_block_respects_char_cap(priors_file):
    for ctx_claim in ("Acme leads the market with the biggest base",
                      "Revenue grew 12% annually across the region"):
        block = style_priors.prior_block("kpi_dashboard", ctx_claim)
        assert block != ""
        assert len(block) <= style_priors.MAX_CHARS


def test_char_cap_actually_binds(priors_file, monkeypatch):
    """A cap the default block never reaches is untested code: shrink
    MAX_CHARS until both enforcement paths bite."""
    claim = "Revenue grew 12% annually across the region"
    full = style_priors.prior_block("chart_slide", claim)
    assert len(full) > 200  # 4 stats — the caps below really bind
    # Regime 1: whole stats are shed first, block stays well-formed
    monkeypatch.setattr(style_priors, "MAX_CHARS", 200)
    shed = style_priors.prior_block("chart_slide", claim)
    assert shed.startswith("STYLE PRIORS") and shed.endswith(".")
    assert len(shed) <= 200
    assert shed.count(";") < full.count(";")  # a stat was dropped whole
    # Regime 2: even the 2-stat floor overflows -> hard truncation
    monkeypatch.setattr(style_priors, "MAX_CHARS", 150)
    hard = style_priors.prior_block("chart_slide", claim)
    assert hard != ""
    assert len(hard) <= 150


def test_non_chart_archetype_returns_empty(priors_file):
    assert style_priors.prior_block("full_bleed_title",
                                    "Acme leads the market") == ""
    assert style_priors.prior_block("agenda_slide",
                                    "Revenue grew 12%") == ""


def test_unroutable_claim_returns_empty(priors_file):
    assert style_priors.prior_block("chart_slide",
                                    "Some words about nothing") == ""


def test_context_missing_from_priors_returns_empty(priors_file):
    # routes to share_mix, which the priors file does not carry
    assert style_priors.prior_block(
        "chart_slide", "Premium accounts for half the mix") == ""

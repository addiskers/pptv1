"""Tag-based exemplar retrieval + its wiring into spec_generator._few_shot."""
import json
import os
import time
from pathlib import Path

from corpus import induce
from deckengine.llm import exemplar_retrieval as er
from deckengine.llm import spec_generator as sg


def _write(p: Path, spec: dict) -> Path:
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


# --- tag derivation (pure) ---------------------------------------------------

def test_derive_tags_chart_spec():
    spec = {"slide_type": "chart_slide",
            "title": "Two-wheelers lead adoption at 62% of units",
            "chart": {"kind": "native_chart", "chart_type": "bar",
                      "highlight": "x"}}
    t = er.derive_tags(spec)
    assert t.archetype == "chart_slide"
    assert t.chart_type == "bar"
    assert t.claim_context == "ranking_comparison"  # "lead" -> ranking


def test_derive_tags_framework_craft():
    spec = {"slide_type": "framework_slide", "title": "Demand stays durable",
            "pathway": {"kind": "chevron_pathway", "steps": ["a"]},
            "blocks": [{"kind": "numbered_block", "number": "1"}]}
    t = er.derive_tags(spec)
    assert "chevron" in t.craft and "numbered_steps" in t.craft


def test_derive_tags_overlay_supplies_firm_and_quality():
    spec = {"slide_type": "chart_slide", "title": "share of mix"}
    t = er.derive_tags(spec, {"firm_style": "bcg_like", "anchor": "great",
                              "det_score": 88})
    assert t.firm_style == "bcg_like"
    assert t.anchor == "great"
    assert t.det_score == 88.0


# --- scoring / ranking (pure) ------------------------------------------------

def test_context_match_outranks_no_match():
    q = er.Query("chart_slide", claim_context="growth")
    grow = er.ExemplarTags("chart_slide", claim_context="growth")
    rank_ = er.ExemplarTags("chart_slide", claim_context="ranking_comparison")
    assert er.score(q, grow) > er.score(q, rank_)


def test_quality_breaks_ties():
    q = er.Query("chart_slide", claim_context="growth")
    great = er.ExemplarTags("chart_slide", claim_context="growth",
                            anchor="great")
    mediocre = er.ExemplarTags("chart_slide", claim_context="growth",
                               anchor="mediocre")
    assert er.score(q, great) > er.score(q, mediocre)


def test_firm_hint_adds_weight():
    q = er.Query("chart_slide", firm_hint="bcg_like")
    match = er.ExemplarTags("chart_slide", firm_style="bcg_like")
    other = er.ExemplarTags("chart_slide", firm_style="mck_like")
    assert er.score(q, match) > er.score(q, other)


# --- select_exemplars over real files ----------------------------------------

def test_select_picks_best_context_match(tmp_path):
    grow = _write(tmp_path / "chart_slide_grow.json",
                  {"slide_type": "chart_slide",
                   "title": "Revenue grew 20% year over year"})
    rank_ = _write(tmp_path / "chart_slide_rank.json",
                   {"slide_type": "chart_slide",
                    "title": "Acme leads the segment on volume"})
    picks = er.select_exemplars("chart_slide", "the market grew sharply",
                                [rank_, grow], tmp_path, k=1)
    assert picks == [grow]


def test_kill_switch_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKENGINE_EXEMPLAR_RETRIEVAL", "0")
    f = _write(tmp_path / "chart_slide_x.json",
               {"slide_type": "chart_slide", "title": "x grew"})
    assert er.select_exemplars("chart_slide", "grew", [f], tmp_path,
                               k=1) == []


def test_overlay_firm_hint_selects_file(tmp_path):
    a = _write(tmp_path / "chart_slide_a.json",
               {"slide_type": "chart_slide", "title": "share of mix"})
    b = _write(tmp_path / "chart_slide_b.json",
               {"slide_type": "chart_slide", "title": "share of mix"})
    (tmp_path / er.OVERLAY_NAME).write_text(json.dumps({
        "chart_slide_b.json": {"firm_style": "bcg_like", "anchor": "great"}}),
        encoding="utf-8")
    picks = er.select_exemplars("chart_slide", "share of mix", [a, b],
                                tmp_path, k=1, firm_hint="bcg_like")
    assert picks == [b]


def test_garbage_file_is_skipped_not_fatal(tmp_path):
    good = _write(tmp_path / "chart_slide_ok.json",
                  {"slide_type": "chart_slide", "title": "x grew"})
    bad = tmp_path / "chart_slide_bad.json"
    bad.write_text("{not json", encoding="utf-8")
    picks = er.select_exemplars("chart_slide", "grew", [bad, good],
                                tmp_path, k=2)
    assert picks == [good]


# --- wiring into _few_shot ---------------------------------------------------

def _install_few_shots(monkeypatch, root: Path) -> Path:
    won = root / "won"
    won.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sg, "_FEW_SHOTS_DIR", root)
    monkeypatch.setattr(sg, "WON_DIR", won)
    return won


def test_few_shot_reaches_induced_slot(tmp_path, monkeypatch):
    # Regression: induced big-firm exemplars land at {archetype}_3.json and
    # up; the old _few_shot only ever read .json + _2.json + won/, so they
    # never reached a prompt. They must now be injectable.
    _install_few_shots(monkeypatch, tmp_path)
    _write(tmp_path / "chart_slide.json",
           {"slide_type": "chart_slide", "title": "base mold"})
    _write(tmp_path / "chart_slide_3.json",
           {"slide_type": "chart_slide",
            "title": "Revenue grew 30% as demand expanded", "INDUCED": 1})
    shot = sg._few_shot("chart_slide", "the market grew fast")
    assert '"INDUCED": 1' in shot


def test_few_shot_best_match_beats_mtime(tmp_path, monkeypatch):
    won = _install_few_shots(monkeypatch, tmp_path)
    match = _write(won / "chart_slide_match.json",
                   {"slide_type": "chart_slide",
                    "title": "Revenue grew 20% in one year", "PICK": "match"})
    _write(won / "chart_slide_newer.json",
           {"slide_type": "chart_slide",
            "title": "Acme leads the field", "PICK": "newer"})
    old = time.time() - 1000  # make the context-matching one the OLDER file
    os.utime(match, (old, old))
    shot = sg._few_shot("chart_slide", "the market grew quickly")
    # both fit in 3 slots, but best-match must rank first (not latest-mtime)
    assert shot.index('"PICK": "match"') < shot.index('"PICK": "newer"')


def test_few_shot_fallback_preserves_historical_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("DECKENGINE_EXEMPLAR_RETRIEVAL", "0")
    won = _install_few_shots(monkeypatch, tmp_path)
    _write(tmp_path / "chart_slide.json", {"slide_type": "chart_slide",
                                           "BASE": 1})
    _write(tmp_path / "chart_slide_2.json", {"slide_type": "chart_slide",
                                             "TWO": 2})
    a = _write(won / "chart_slide_a.json", {"slide_type": "chart_slide",
                                            "W": "a"})
    _write(won / "chart_slide_b.json", {"slide_type": "chart_slide",
                                        "W": "b"})
    old = time.time() - 1000  # b is newer -> latest-won rule keeps b, drops a
    os.utime(a, (old, old))
    shot = sg._few_shot("chart_slide", "anything")
    assert '"BASE": 1' in shot and '"TWO": 2' in shot and '"W": "b"' in shot
    assert '"W": "a"' not in shot


# --- induce.apply_approved feeds the overlay ---------------------------------

def test_apply_approved_writes_retrieval_overlay(tmp_path):
    work = tmp_path / "work"
    d = work / "induce" / "deck1_005"
    d.mkdir(parents=True)
    _write(d / "neutralized.json",
           {"slide_type": "chart_slide", "title": "Acme grew"})
    (work / "classified.jsonl").write_text(json.dumps({
        "slide_id": "deck1:005", "claim_context": "growth",
        "firm_style": "bcg_like", "anchor": "great",
        "chart": {"chart_type": "bar"}}) + "\n", encoding="utf-8")
    (work / "scores.jsonl").write_text(json.dumps({
        "slide_id": "deck1:005", "score": 82}) + "\n", encoding="utf-8")
    few = tmp_path / "few"
    few.mkdir()
    gold = tmp_path / "gold"
    gold.mkdir()
    res = induce.apply_approved(work, ["deck1:005"], few_shots=few,
                                goldens=gold)
    assert res["applied"] == 1
    assert (few / "chart_slide_2.json").is_file()
    overlay = json.loads((few / er.OVERLAY_NAME).read_text(encoding="utf-8"))
    entry = overlay["chart_slide_2.json"]
    assert entry["firm_style"] == "bcg_like"
    assert entry["anchor"] == "great"
    assert entry["det_score"] == 82.0

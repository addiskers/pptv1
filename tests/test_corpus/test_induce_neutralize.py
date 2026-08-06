"""Exemplar induction + neutralization (all LLM/COM calls mocked)."""
import json
from pathlib import Path

from corpus import induce, neutralize


# --- leak gate: the deterministic IP safety ----------------------------------

def test_leak_gate_catches_planted_name_and_number():
    source = "Contoso captured 4,217 units across the Baltics in 2024."
    neutral = {"title": "Contoso leads with 4,217 units",
               "slide_type": "bullet_content"}
    leaked = neutralize.leak_gate(neutral, source)
    assert "contoso" in leaked
    assert "4217" in leaked


def test_leak_gate_clean_when_rewritten():
    source = "Contoso captured 4,217 units across the Baltics in 2024."
    neutral = {"title": "Acme leads with 5,000 units in the region",
               "slide_type": "bullet_content"}
    assert neutralize.leak_gate(neutral, source) == []


def test_leak_gate_ignores_generic_words_and_years():
    source = "Market Revenue Growth reached a peak in 2024 and 2025."
    neutral = {"title": "Market Revenue Growth peaked in 2024",
               "slide_type": "x"}
    # 'Market/Revenue/Growth' are generic stopwords; 2024/2025 are years
    assert neutralize.leak_gate(neutral, source) == []


def test_neutralize_spec_rejects_when_leaked(monkeypatch):
    src = "Contoso hit 4,217 units."
    # LLM 'rewrite' that lazily keeps the real name -> gate must reject
    monkeypatch.setattr(neutralize, "_neutralize_call",
                        lambda spec: {"title": "Contoso hit 4,217 units"})
    out, leaked = neutralize.neutralize_spec(
        {"title": "Contoso hit 4,217 units"}, src, "bullet_content")
    assert out is None
    assert "contoso" in leaked


def test_neutralize_spec_accepts_clean_rewrite(monkeypatch):
    src = "Contoso hit 4,217 units."
    monkeypatch.setattr(neutralize, "_neutralize_call",
                        lambda spec: {"title": "Acme hit 5,000 units"})
    out, leaked = neutralize.neutralize_spec(
        {"title": "Contoso hit 4,217 units"}, src, "bullet_content")
    assert leaked == []
    assert out["title"] == "Acme hit 5,000 units"
    assert out["slide_type"] == "bullet_content"


# --- candidate selection -----------------------------------------------------

def _write(work: Path):
    work.mkdir(parents=True, exist_ok=True)

    def dump(name, rows):
        (work / name).write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    idx, sc, cl = [], [], []
    # 5 slides across 3 decks; d1 has two great chart slides (dedup to 1)
    specs = [
        ("d1:000", "d1", 90, "chart", "great", 0.9),
        ("d1:001", "d1", 88, "chart", "great", 0.9),   # same deck -> skipped
        ("d2:000", "d2", 85, "dashboard", "great", 0.8),
        ("d3:000", "d3", 80, "chart", "mediocre", 0.9),  # not great -> out
        ("d3:001", "d3", 70, "framework", "great", 0.5),  # low conf -> out
    ]
    for sid, deck, score, role, anchor, conf in specs:
        idx.append({"slide_id": sid, "deck_id": deck,
                    "png_path": f"/png/{sid}.png", "extracted_text": "x",
                    "phash": "0" * 64})
        sc.append({"slide_id": sid, "score": score, "parts": {}})
        cl.append({"slide_id": sid, "slide_role": role, "anchor": anchor,
                   "confidence": conf})
    dump("index.jsonl", idx)
    dump("scores.jsonl", sc)
    dump("classified.jsonl", cl)


def test_select_candidates_ranks_dedups_filters(tmp_path):
    work = tmp_path / "work"
    _write(work)
    cands = induce.select_candidates(work, total_cap=30)
    ids = [c["slide_id"] for c in cands]
    assert ids == ["d1:000", "d2:000"]  # best per deck; great+confident only
    assert cands[0]["archetype"] == "chart_slide"
    assert cands[1]["archetype"] == "kpi_dashboard"


def test_per_archetype_cap(tmp_path):
    work = tmp_path / "work"
    _write(work)
    # cap chart_slide at 0 -> only the dashboard survives
    cands = induce.select_candidates(work, total_cap=30, per_archetype_cap=0)
    assert all(c["archetype"] != "chart_slide" for c in cands)


# --- the induction loop ------------------------------------------------------

def _bullet_spec():
    return {"slide_type": "bullet_content",
            "title": "Contoso grew revenue 20% to 4,217 in 2024",
            "bullets": [{"text": "Contoso led every region with 4,217 units"}]}


def _install_loop(monkeypatch, tmp_path, fidelity_scores):
    """Wire draft -> render -> fidelity so induce_one runs offline."""
    calls = {"draft": 0, "fidelity": 0}

    def fake_draft(schema, png, text, feedback):
        calls["draft"] += 1
        return _bullet_spec()
    monkeypatch.setattr(induce, "_draft_call", fake_draft)

    def fake_render(spec_model, workdir, tag):
        p = workdir / f"{tag}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n")
        return p
    monkeypatch.setattr(induce, "_render_png", fake_render)

    seq = list(fidelity_scores)

    def fake_fidelity(original, replica):
        calls["fidelity"] += 1
        s = seq.pop(0) if seq else 5
        return {"score": s, "gaps": ["tighter hierarchy"] if s < 4 else []}
    monkeypatch.setattr(induce, "_fidelity_call", fake_fidelity)

    # clean neutralize
    monkeypatch.setattr(
        neutralize, "_neutralize_call",
        lambda spec: {**spec, "title": "Acme grew revenue 30% to 5,000",
                      "bullets": [{"text": "Acme led every region with "
                                   "5,000 units"}]})
    return calls


def _cand(tmp_path):
    png = tmp_path / "src.png"
    png.write_bytes(b"\x89PNG\r\n")
    return {"slide_id": "d1:000", "deck_id": "d1", "png_path": str(png),
            "extracted_text": "Contoso grew revenue 20% to 4,217 in 2024",
            "archetype": "bullet_content", "score": 90}


def test_induce_one_passes_on_high_fidelity(monkeypatch, tmp_path):
    calls = _install_loop(monkeypatch, tmp_path, [5])
    r = induce.induce_one(_cand(tmp_path), tmp_path / "work")
    assert r["ok"] is True
    assert r["fidelity"] == 5
    assert r["leaked"] == []
    assert calls["draft"] == 1  # no repair needed
    neu = (tmp_path / "work" / "induce" / "d1_000" / "neutralized.json")
    assert "Contoso" not in neu.read_text(encoding="utf-8")


def test_induce_one_repairs_then_passes(monkeypatch, tmp_path):
    calls = _install_loop(monkeypatch, tmp_path, [3, 5])  # low, then good
    r = induce.induce_one(_cand(tmp_path), tmp_path / "work")
    assert r["ok"] is True
    assert calls["draft"] == 2      # one repair round
    assert calls["fidelity"] == 2


def test_induce_one_fails_low_fidelity(monkeypatch, tmp_path):
    _install_loop(monkeypatch, tmp_path, [2, 2, 2])  # never clears bar
    r = induce.induce_one(_cand(tmp_path), tmp_path / "work")
    assert r["ok"] is False


def test_estimate_and_budget_never_call_llm(monkeypatch, tmp_path):
    work = tmp_path / "work"
    _write(work)

    def boom(*a, **k):
        raise AssertionError("no LLM in estimate/budget path")
    monkeypatch.setattr(induce, "_draft_call", boom)
    est = induce.run_induce(work, estimate=True)
    assert est["pending"] >= 1 and "est_usd" in est
    import pytest
    with pytest.raises(SystemExit):
        induce.run_induce(work, budget_usd=0.0)


# --- apply -------------------------------------------------------------------

def test_apply_copies_to_fewshots_and_goldens(monkeypatch, tmp_path):
    _install_loop(monkeypatch, tmp_path, [5])
    work = tmp_path / "work"
    induce.induce_one(_cand(tmp_path), work)
    fs = tmp_path / "few_shots"
    gold = tmp_path / "goldens"
    fs.mkdir()
    gold.mkdir()
    res = induce.apply_approved(work, ["d1:000"], few_shots=fs, goldens=gold)
    assert res["applied"] == 1
    assert (fs / "bullet_content_2.json").is_file()
    golds = list(gold.glob("corpus_*.json"))
    assert len(golds) == 1
    deck = json.loads(golds[0].read_text(encoding="utf-8"))
    assert deck["slides"][0]["slide_type"] == "bullet_content"

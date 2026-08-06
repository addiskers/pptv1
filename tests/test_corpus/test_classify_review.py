"""Classification + contact-sheet tests — provider stubbed, no network."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from corpus import classify, review
from corpus.classify import SlideClassification


# --- fixtures ----------------------------------------------------------------

def make_png(path: Path, w=320, h=180, color=(200, 40, 40)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), color).save(path)


def valid_payload():
    return {
        "slide_role": "chart",
        "claim_context": "growth",
        "chart": {"chart_type": "bar", "n_series": 1, "n_categories": 4,
                  "value_labels": True, "endpoint_labels": False,
                  "avg_or_target_line": False, "delta_brackets": False,
                  "cagr_arrow": False, "forecast_dashed": False,
                  "indexed_base100": False, "area_fill": False,
                  "series_highlight": False, "sorted_desc": True,
                  "annotations": 1, "legend_position": "none"},
        "layout": {"structure": "single", "has_kicker": True,
                   "has_bottom_band": False, "has_source_footer": True},
        "density": 3, "text_amount": "light",
        "craft_elements": ["big_number"], "title_is_action": True,
        "anchor": "great", "firm_style": "mck_like", "confidence": 0.8,
    }


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def setup_work(tmp_path: Path) -> Path:
    """4 slides: 000/001 keep, 002 keep-but-dup, 003 filtered out."""
    work = tmp_path / "work"
    colors = [(200, 40, 40), (40, 200, 40), (40, 40, 200), (9, 9, 9)]
    texts = ["alpha slide text", "beta slide text", "gamma dup text",
             "delta filtered text"]
    rows = []
    for i in range(4):
        sid = f"deckA:{i:03d}"
        png = work / "png" / "deckA" / f"slide{i:03d}.png"
        make_png(png, color=colors[i])
        rows.append({"deck_id": "deckA", "slide_id": sid,
                     "slide_index": i, "png_path": png.as_posix(),
                     "extracted_text": texts[i],
                     "dup_of": "deckA:001" if i == 2 else None})
    write_jsonl(work / "index.jsonl", rows)
    write_jsonl(work / "filtered.jsonl", [
        {"slide_id": "deckA:000", "keep": True, "reasons": []},
        {"slide_id": "deckA:001", "keep": True, "reasons": []},
        {"slide_id": "deckA:002", "keep": True, "reasons": []},
        {"slide_id": "deckA:003", "keep": False, "reasons": ["logo"]},
    ])
    return work


class StubVision:
    """Returns valid JSON; a slide whose prompt text contains a fail
    marker gets one invalid payload first (exercises the repair loop)."""

    def __init__(self, fail_first_for=()):
        self.calls = 0
        self.parts_log = []
        self._pending_fail = set(fail_first_for)

    def __call__(self, schema, parts):
        self.calls += 1
        self.parts_log.append(parts)
        text = " ".join(v for k, v in parts if k == "text")
        for marker in list(self._pending_fail):
            if marker in text:
                self._pending_fail.discard(marker)
                bad = valid_payload()
                bad["craft_elements"] = ["not_a_real_tag"]
                return bad
        return valid_payload()


def read_classified(work: Path) -> list[SlideClassification]:
    lines = (work / "classified.jsonl").read_text(
        encoding="utf-8").splitlines()
    return [SlideClassification.model_validate_json(li)
            for li in lines if li.strip()]


# --- classify ----------------------------------------------------------------

def test_classify_survivors_with_repair(tmp_path, monkeypatch):
    work = setup_work(tmp_path)
    stub = StubVision(fail_first_for={"beta"})
    monkeypatch.setattr(classify, "_vision_call", stub)
    summary = classify.run_classify(work, anchors=tmp_path / "none")
    assert summary["classified"] == 2
    assert summary["errors"] == 0
    assert stub.calls == 3  # 2 slides + 1 repair for the beta slide
    recs = read_classified(work)
    # dup (002) and keep=false (003) never classified
    assert {r.slide_id for r in recs} == {"deckA:000", "deckA:001"}
    for r in recs:
        assert r.anchor == "great"
        assert r.craft_elements == ["big_number"]
    assert not (work / "classify_errors.jsonl").exists()
    # anchors dir missing -> exactly one image (the slide) per call
    for parts in stub.parts_log:
        assert sum(1 for k, _ in parts if k == "image") == 1
    # the repair call must feed the validation errors back to the model
    repairs = [parts for parts in stub.parts_log
               if any(k == "text" and "failed validation" in v
                      for k, v in parts)]
    assert len(repairs) == 1
    err_text = " ".join(v for k, v in repairs[0] if k == "text")
    assert "not_a_real_tag" in err_text  # actual pydantic error rides
    assert "beta" in err_text  # repair re-sends the failing slide


def test_anchor_images_ride_in_prompt(tmp_path, monkeypatch):
    work = setup_work(tmp_path)
    anchors = tmp_path / "anchors"
    for name in ("great", "mediocre", "bad"):
        make_png(anchors / f"{name}.png", w=64, h=48)
    stub = StubVision()
    monkeypatch.setattr(classify, "_vision_call", stub)
    classify.run_classify(work, anchors=anchors)
    for parts in stub.parts_log:  # 3 anchors + the slide itself
        assert sum(1 for k, _ in parts if k == "image") == 4


def test_cache_hit_on_second_run(tmp_path, monkeypatch):
    work = setup_work(tmp_path)
    stub = StubVision()
    monkeypatch.setattr(classify, "_vision_call", stub)
    classify.run_classify(work, anchors=tmp_path / "none")
    first_calls = stub.calls
    assert first_calls == 2
    cache = list((work / "cache" / "classify").glob("*.json"))
    assert len(cache) == 2
    (work / "classified.jsonl").unlink()
    summary = classify.run_classify(work, anchors=tmp_path / "none")
    assert summary["classified"] == 2
    assert summary["cached"] == 2
    assert stub.calls == first_calls  # served from cache, no new calls
    assert {r.slide_id for r in read_classified(work)} == {
        "deckA:000", "deckA:001"}
    # cache key must include PROMPT_VERSION: bumping it invalidates
    monkeypatch.setattr(classify, "PROMPT_VERSION", "classify-v999")
    (work / "classified.jsonl").unlink()
    summary = classify.run_classify(work, anchors=tmp_path / "none")
    assert summary["cached"] == 0
    assert stub.calls == first_calls + 2
    # ...and the model id: a different model never reuses old entries
    monkeypatch.setattr(classify, "_cache_model_id",
                        lambda: "other-model")
    (work / "classified.jsonl").unlink()
    summary = classify.run_classify(work, anchors=tmp_path / "none")
    assert summary["cached"] == 0
    assert stub.calls == first_calls + 4


def test_resume_skips_already_classified(tmp_path, monkeypatch):
    work = setup_work(tmp_path)
    stub = StubVision()
    monkeypatch.setattr(classify, "_vision_call", stub)
    classify.run_classify(work, anchors=tmp_path / "none")
    summary = classify.run_classify(work, anchors=tmp_path / "none")
    assert summary["classified"] == 0
    assert summary["pending"] == 0
    assert summary["skipped_done"] == 2
    assert stub.calls == 2  # nothing re-called
    assert len(read_classified(work)) == 2  # no duplicate lines


def test_torn_classified_line_does_not_brick_resume(tmp_path,
                                                    monkeypatch):
    work = setup_work(tmp_path)
    stub = StubVision()
    monkeypatch.setattr(classify, "_vision_call", stub)
    classify.run_classify(work, anchors=tmp_path / "none")
    with (work / "classified.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"slide_id": "deckA:0')  # torn, no newline
    summary = classify.run_classify(work, anchors=tmp_path / "none")
    assert summary["classified"] == 0
    assert stub.calls == 2


def test_estimate_makes_no_calls(tmp_path, monkeypatch, capsys):
    work = setup_work(tmp_path)
    stub = StubVision()
    monkeypatch.setattr(classify, "_vision_call", stub)
    classify.main(["--work", str(work), "--estimate"])
    out = json.loads(capsys.readouterr().out)
    assert out["pending"] == 2
    assert out["uncached"] == 2
    assert out["est_usd"] == pytest.approx(
        2 * classify.COST_PER_CALL_USD)
    assert stub.calls == 0
    assert not (work / "classified.jsonl").exists()


def test_budget_abort_raises_systemexit(tmp_path, monkeypatch):
    work = setup_work(tmp_path)
    stub = StubVision()
    monkeypatch.setattr(classify, "_vision_call", stub)
    with pytest.raises(SystemExit):
        classify.run_classify(work, budget_usd=1e-9,
                              anchors=tmp_path / "none")
    assert stub.calls == 0  # aborted before the first call
    assert not (work / "classified.jsonl").exists()


def test_downscale_caps_long_edge(tmp_path):
    big = tmp_path / "big.png"
    make_png(big, w=2048, h=512)
    out = classify.downscale_png(big.read_bytes())
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (1024, 256)  # long edge 1024, aspect kept
    small = tmp_path / "small.png"
    make_png(small, w=300, h=200)
    data = small.read_bytes()
    assert classify.downscale_png(data) == data  # untouched


# --- review ------------------------------------------------------------------

def setup_review(tmp_path, monkeypatch) -> Path:
    work = setup_work(tmp_path)
    stub = StubVision()
    monkeypatch.setattr(classify, "_vision_call", stub)
    classify.run_classify(work, anchors=tmp_path / "none")
    write_jsonl(work / "scores.jsonl", [
        {"slide_id": "deckA:000", "score": 82, "parts": {"align": 0.9}},
        {"slide_id": "deckA:001", "score": 47, "parts": {"align": 0.4}},
    ])
    return work


def test_review_html_lists_slides_and_pngs(tmp_path, monkeypatch):
    work = setup_review(tmp_path, monkeypatch)
    summary = review.run_review(work)
    text = Path(summary["out"]).read_text(encoding="utf-8")
    assert summary["rows"] == 2
    assert "deckA:000" in text and "deckA:001" in text
    assert "slide000.png" in text and "slide001.png" in text
    assert "82" in text and "47" in text  # det scores
    assert "great" in text and "chart" in text and "growth" in text
    assert "big_number" in text
    assert 'type="checkbox"' in text
    assert "deck deckA" in text  # no clusters.jsonl -> grouped by deck


def test_review_groups_by_cluster_when_present(tmp_path, monkeypatch):
    work = setup_review(tmp_path, monkeypatch)
    write_jsonl(work / "clusters.jsonl", [
        {"cluster_id": "c7", "slide_ids": ["deckA:000"],
         "exemplar_slide_ids": ["deckA:000"], "size": 1}])
    summary = review.run_review(work)
    text = Path(summary["out"]).read_text(encoding="utf-8")
    assert "cluster c7" in text
    assert "unclustered" in text  # deckA:001 belongs to no cluster


def test_apply_merges_only_approved_ids(tmp_path, monkeypatch):
    work = setup_review(tmp_path, monkeypatch)
    approved = tmp_path / "approved.txt"
    approved.write_text("deckA:000\n\n# a comment\n", encoding="utf-8")
    summary = review.run_apply(work, approved)
    rows = [json.loads(li) for li in
            Path(summary["out"]).read_text(encoding="utf-8").splitlines()
            if li.strip()]
    assert summary["approved"] == 1
    assert len(rows) == 1
    assert rows[0]["slide_id"] == "deckA:000"
    assert rows[0]["det_score"] == 82
    assert rows[0]["score_parts"] == {"align": 0.9}
    assert rows[0]["classification"]["slide_role"] == "chart"
    assert rows[0]["png_path"].endswith("slide000.png")

"""Cluster + patterns tests — synthetic jsonl fixtures only, no COM,
no network, no LLM. Records are written as raw dicts (the readers are
schema-tolerant by design)."""
import json
from pathlib import Path

from corpus import cluster, patterns


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# --- cluster fixtures ---------------------------------------------------------

def chart_stats() -> dict:
    return {"n_shapes": 4, "n_textboxes": 1, "n_pictures": 1,
            "n_tables": 0, "n_charts": 2, "n_groups": 0,
            "chart_xml_types": ["barChart"], "has_smartart": False,
            "x_edges": [40, 900], "y_edges": [30, 500]}


def text_stats() -> dict:
    return {"n_shapes": 6, "n_textboxes": 6, "n_pictures": 0,
            "n_tables": 0, "n_charts": 0, "n_groups": 0,
            "chart_xml_types": [], "has_smartart": False,
            "x_edges": [440, 500], "y_edges": [250, 300]}


def index_row(slide_id: str, stats: dict | None, phash: str) -> dict:
    return {"slide_id": slide_id, "deck_id": slide_id.split(":")[0],
            "shape_stats": stats, "phash": phash,
            "source_path": "src/deck.pptx"}


def build_two_families(work: Path) -> None:
    rows = []
    scores = []
    kept = []
    a_scores = [90, 70, 80, 60]
    b_scores = [85, 75, 65, 55]
    for i in range(4):
        sid = f"dA:{i:03d}"
        rows.append(index_row(sid, chart_stats(), "0" * 48 + f"{i:016x}"))
        scores.append({"slide_id": sid, "score": a_scores[i], "parts": {}})
        kept.append({"slide_id": sid, "keep": True, "reasons": []})
    for i in range(4):
        sid = f"dB:{i:03d}"
        rows.append(index_row(
            sid, text_stats(), "f" * 48 + f"{(2 ** 64 - 1 - i):016x}"))
        scores.append({"slide_id": sid, "score": b_scores[i], "parts": {}})
        kept.append({"slide_id": sid, "keep": True, "reasons": []})
    # filtered-out slide must never reach a cluster
    rows.append(index_row("dA:009", chart_stats(), "0" * 64))
    scores.append({"slide_id": "dA:009", "score": 99, "parts": {}})
    kept.append({"slide_id": "dA:009", "keep": False,
                 "reasons": ["boilerplate"]})
    write_jsonl(work / "index.jsonl", rows)
    write_jsonl(work / "scores.jsonl", scores)
    write_jsonl(work / "filtered.jsonl", kept)


def read_clusters(work: Path) -> list[cluster.ClusterRecord]:
    text = (work / "clusters.jsonl").read_text(encoding="utf-8")
    return [cluster.ClusterRecord.model_validate_json(li)
            for li in text.splitlines() if li.strip()]


# --- cluster tests ------------------------------------------------------------

def test_two_layout_families_form_two_clusters(tmp_path):
    work = tmp_path / "work"
    build_two_families(work)
    summary = cluster.run_cluster(work)
    assert summary["n_slides"] == 8  # dA:009 filtered out
    assert summary["n_clusters"] == 2
    assert summary["sizes"] == {4: 2}
    recs = read_clusters(work)
    assert [r.cluster_id for r in recs] == ["c000", "c001"]
    # highest-score slide overall seeds the first cluster
    assert recs[0].slide_ids == ["dA:000", "dA:002", "dA:001", "dA:003"]
    assert recs[1].slide_ids == ["dB:000", "dB:001", "dB:002", "dB:003"]
    # exemplars: top <=3 by det score, highest first
    assert recs[0].exemplar_slide_ids == ["dA:000", "dA:002", "dA:001"]
    assert recs[1].exemplar_slide_ids == ["dB:000", "dB:001", "dB:002"]
    assert all("dA:009" not in r.slide_ids for r in recs)


def test_clustering_is_deterministic_across_runs(tmp_path):
    work = tmp_path / "work"
    build_two_families(work)
    s1 = cluster.run_cluster(work)
    first = (work / "clusters.jsonl").read_text(encoding="utf-8")
    s2 = cluster.run_cluster(work)
    second = (work / "clusters.jsonl").read_text(encoding="utf-8")
    assert s1 == s2
    assert first == second  # overwrite, byte-identical


def test_pdf_only_records_cluster_by_phash(tmp_path):
    work = tmp_path / "work"
    rows, scores = [], []
    low = [("p:000", "0" * 64, 90), ("p:001", "0" * 63 + "1", 80),
           ("p:002", "0" * 63 + "3", 70)]
    high = [("q:000", "f" * 64, 85), ("q:001", "f" * 63 + "e", 75),
            ("q:002", "f" * 63 + "c", 65)]
    for sid, ph, sc in low + high:
        rows.append(index_row(sid, None, ph))  # shape_stats None: PDF
        scores.append({"slide_id": sid, "score": sc, "parts": {}})
    write_jsonl(work / "index.jsonl", rows)
    write_jsonl(work / "scores.jsonl", scores)
    # no filtered.jsonl at all -> every slide kept
    summary = cluster.run_cluster(work)
    assert summary["n_clusters"] == 2
    assert summary["sizes"] == {3: 2}
    recs = read_clusters(work)
    assert recs[0].slide_ids == ["p:000", "p:001", "p:002"]
    assert recs[1].slide_ids == ["q:000", "q:001", "q:002"]


def test_torn_trailing_lines_tolerated(tmp_path):
    work = tmp_path / "work"
    build_two_families(work)
    for name in ("index.jsonl", "filtered.jsonl", "scores.jsonl"):
        with (work / name).open("a", encoding="utf-8") as f:
            f.write('{"slide_id": "to')  # torn, no newline
    summary = cluster.run_cluster(work)
    assert summary["n_clusters"] == 2


# --- patterns fixtures ----------------------------------------------------------

def classified_row(sid: str, **over) -> dict:
    """One classified.jsonl line in the REAL SlideClassification dump
    shape from corpus/classify.py: nested `chart` (boolean feature
    flags, int annotations) + `layout` objects, `craft_elements`,
    great/mediocre/bad anchors, *_like firm styles. The flat kwargs
    (chart_type=, features=, craft=, structure=, has_bottom_band=,
    has_source_footer=, density=) are folded into that shape."""
    chart_type = over.pop("chart_type", "bar")
    features = over.pop("features", [])
    craft = over.pop("craft", [])
    structure = over.pop("structure", "single")
    bottom = over.pop("has_bottom_band", False)
    footer = over.pop("has_source_footer", True)
    density = over.pop("density", 3)
    row = {
        "slide_id": sid, "slide_role": "chart",
        "claim_context": "ranking_comparison",
        "chart": {
            "chart_type": chart_type, "n_series": 1, "n_categories": 5,
            "value_labels": "value_labels" in features,
            "endpoint_labels": "endpoint_labels" in features,
            "avg_or_target_line": False, "delta_brackets": False,
            "cagr_arrow": False, "forecast_dashed": False,
            "indexed_base100": False, "area_fill": False,
            "series_highlight": "series_highlight" in features,
            "sorted_desc": "sorted_desc" in features,
            "annotations": 1 if "annotations" in features else 0,
            "legend_position": "none"},
        "layout": {"structure": structure, "has_kicker": False,
                   "has_bottom_band": bottom,
                   "has_source_footer": footer},
        "density": density, "text_amount": "light",
        "craft_elements": craft, "title_is_action": True,
        "anchor": "great", "firm_style": "mck_like", "confidence": 0.9}
    row.update(over)
    return row


def build_pattern_corpus(work: Path) -> None:
    idx, sc, cl = [], [], []

    def add(sid, deck, source, score, **over):
        idx.append({"slide_id": sid, "deck_id": deck,
                    "source_path": source, "phash": "0" * 64})
        sc.append({"slide_id": sid, "score": score, "parts": {}})
        cl.append(classified_row(sid, **over))

    for i, firm in enumerate(["mck_like", "mck_like",
                              "bain_like", "bain_like"]):
        add(f"s{i + 1}", "d1", "own/deckA.pptx", 80,
            features=["value_labels", "sorted_desc"],
            craft=["so_what_band"], has_bottom_band=True, firm_style=firm)
    for i in range(2):
        add(f"s{i + 5}", "d2", "other/deckB.pptx", 80, chart_type="line",
            features=["endpoint_labels"], structure="two_col",
            density=2, title_is_action=False, firm_style="bcg_like")
    add("s7", "d3", "other/deckC.pptx", 80, chart_type="donut_pie",
        claim_context="benchmark", slide_role="dashboard",
        structure="grid", craft=["kpi_cards"], density=2,
        firm_style="bcg_like")
    # excluded: anchor below great / low confidence / low det score
    add("s8", "d2", "other/deckB.pptx", 80, anchor="mediocre",
        firm_style="bcg_like")
    add("s9", "d2", "other/deckB.pptx", 80, confidence=0.5,
        firm_style="bcg_like")
    add("s10", "d2", "other/deckB.pptx", 40, firm_style="bcg_like")
    write_jsonl(work / "index.jsonl", idx)
    write_jsonl(work / "scores.jsonl", sc)
    write_jsonl(work / "classified.jsonl", cl)


# --- patterns tests -------------------------------------------------------------

def test_exact_frequencies_and_min_support(tmp_path):
    work = tmp_path / "work"
    build_pattern_corpus(work)
    out = tmp_path / "priors.json"
    data = patterns.run_patterns(work, out, min_support=2)
    assert json.loads(out.read_text(encoding="utf-8")) == data
    assert data["version"] == 1
    assert data["n_slides_total"] == 10
    assert data["n_slides_high_quality"] == 7

    cv = data["chart_variants"]
    assert set(cv) == {"bar", "line"}  # donut_pie n=1 < min_support
    assert cv["bar"]["n"] == 4
    assert cv["bar"]["features"] == {"sorted_desc": 1.0,
                                     "value_labels": 1.0}
    assert cv["line"]["features"] == {}  # endpoint_labels not renderable

    ctx = data["by_claim_context"]
    assert set(ctx) == {"ranking_comparison"}  # benchmark n=1 dropped
    rank = ctx["ranking_comparison"]
    assert rank["n"] == 6
    assert rank["chart_type_freq"] == {"bar": 0.6667, "line": 0.3333}
    assert rank["top_features"] == {"sorted_desc": 0.6667,
                                    "value_labels": 0.6667}
    assert rank["craft_freq"] == {"so_what_band": 0.6667}

    lp = data["layout_patterns"]
    assert set(lp) == {"chart"}  # dashboard n=1 dropped
    assert lp["chart"]["structure_freq"] == {"single": 0.6667,
                                             "two_col": 0.3333}
    assert lp["chart"]["has_bottom_band"] == 0.6667
    assert lp["chart"]["has_source_footer"] == 1.0

    g = data["global"]
    assert g["density_mean"] == 2.5714  # (4*3 + 2*2 + 2) / 7
    assert g["title_is_action_rate"] == 0.7143
    assert g["craft_freq"] == {"so_what_band": 0.5714,
                               "kpi_cards": 0.1429}

    assert data["capability_gaps"] == {"endpoint_labels": 0.2857}
    prov = data["provenance"]
    assert prov["n_decks"] == 3
    assert prov["firm_style_mix"] == {"bcg_like": 0.4286,
                                      "bain_like": 0.2857,
                                      "mck_like": 0.2857}


def test_loosened_anchor_admits_mediocre(tmp_path):
    work = tmp_path / "work"
    build_pattern_corpus(work)
    data = patterns.run_patterns(work, tmp_path / "p.json",
                                 min_quality_anchor="mediocre",
                                 min_support=2)
    assert data["n_slides_high_quality"] == 8  # s8 now included


def test_own_glob_doubles_weight(tmp_path):
    work = tmp_path / "work"
    build_pattern_corpus(work)
    data = patterns.run_patterns(work, tmp_path / "p.json",
                                 own_glob="own/*", min_support=2)
    rank = data["by_claim_context"]["ranking_comparison"]
    # own deck: 4 slides at w=2 -> bar 8/10, line 2/10
    assert rank["chart_type_freq"] == {"bar": 0.8, "line": 0.2}
    assert data["capability_gaps"] == {"endpoint_labels": 0.1818}  # 2/11


def test_firm_cap_rebalances_to_half(tmp_path):
    work = tmp_path / "work"
    idx, sc, cl = [], [], []
    for i in range(8):
        sid = f"m{i}"
        idx.append({"slide_id": sid, "deck_id": "dm",
                    "source_path": "x/m.pptx", "phash": "0" * 64})
        sc.append({"slide_id": sid, "score": 80, "parts": {}})
        cl.append(classified_row(sid, claim_context="growth",
                                 craft=["so_what_band"],
                                 firm_style="mck_like"))
    for i in range(2):
        sid = f"b{i}"
        idx.append({"slide_id": sid, "deck_id": "db",
                    "source_path": "x/b.pptx", "phash": "0" * 64})
        sc.append({"slide_id": sid, "score": 80, "parts": {}})
        cl.append(classified_row(sid, claim_context="growth", craft=[],
                                 firm_style="bcg_like"))
    write_jsonl(work / "index.jsonl", idx)
    write_jsonl(work / "scores.jsonl", sc)
    write_jsonl(work / "classified.jsonl", cl)
    data = patterns.run_patterns(work, tmp_path / "p.json", min_support=2)
    # mck held 80% of raw weight; after the cap both firms sit at 50%
    assert data["provenance"]["firm_style_mix"] == {"bcg_like": 0.5,
                                                    "mck_like": 0.5}
    assert data["global"]["craft_freq"] == {"so_what_band": 0.5}


def test_checklist_only_references_whitelisted_names(tmp_path):
    work = tmp_path / "work"
    build_pattern_corpus(work)
    data = patterns.run_patterns(work, tmp_path / "p.json", min_support=2)
    checklist = data["judge_craft_checklist"]
    assert 0 < len(checklist) <= 6
    allowed = patterns.RENDERABLE_FEATURES | patterns.RENDERABLE_CRAFT
    for entry in checklist:
        assert entry.split(":", 1)[0] in allowed
    joined = " ".join(checklist)
    assert "endpoint_labels" not in joined  # gaps never make the list
    # highest-frequency signals surface
    assert any(e.startswith("value_labels:") for e in checklist)
    assert any(e.startswith("so_what_band:") for e in checklist)


def test_flat_legacy_rows_still_aggregate(tmp_path):
    """Hand-built rows with flat chart_type/features/craft keys (the
    pre-nested convenience shape) must aggregate identically."""
    work = tmp_path / "work"
    idx, sc, cl = [], [], []
    for i in range(2):
        sid = f"f{i}"
        idx.append({"slide_id": sid, "deck_id": "df",
                    "source_path": "x/f.pptx", "phash": "0" * 64})
        sc.append({"slide_id": sid, "score": 80, "parts": {}})
        cl.append({"slide_id": sid, "anchor": "great", "confidence": 0.9,
                   "chart_type": "bar", "features": ["value_labels"],
                   "craft": ["so_what_band"], "slide_role": "chart",
                   "claim_context": "growth", "structure": "single",
                   "has_bottom_band": True, "has_source_footer": True,
                   "density": 3, "title_is_action": True,
                   "firm_style": "mck_like"})
    write_jsonl(work / "index.jsonl", idx)
    write_jsonl(work / "scores.jsonl", sc)
    write_jsonl(work / "classified.jsonl", cl)
    data = patterns.run_patterns(work, tmp_path / "p.json", min_support=2)
    assert data["chart_variants"]["bar"]["features"] == {
        "value_labels": 1.0}
    assert data["by_claim_context"]["growth"]["craft_freq"] == {
        "so_what_band": 1.0}
    assert data["layout_patterns"]["chart"]["structure_freq"] == {
        "single": 1.0}
    assert data["layout_patterns"]["chart"]["has_bottom_band"] == 1.0

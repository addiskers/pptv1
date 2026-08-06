"""Style priors wired into generation prompts + judge rubric (mocked)."""
import json

from deckengine.llm import style_priors
from deckengine.llm import spec_generator as sg
from deckengine.schema.slide_types import ChartSlideSpec

PRIORS = {
    "version": 1,
    "by_claim_context": {
        "ranking_comparison": {
            "n": 100,
            "chart_type_freq": {"bar": 0.7, "line": 0.2},
            "top_features": {"sorted_desc": 0.8, "value_labels": 0.9},
            "craft_freq": {"so_what_band": 0.4},
        }
    },
    "judge_craft_checklist": ["one highlighted series, rest muted",
                              "a so-what callout under the evidence"],
}


def _install_priors(monkeypatch, tmp_path, data):
    p = tmp_path / "style_priors.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(style_priors, "PRIORS_PATH", p)
    style_priors.load_priors.cache_clear()


def test_generate_slide_prompt_carries_priors(monkeypatch, tmp_path):
    _install_priors(monkeypatch, tmp_path, PRIORS)
    prompts = []
    clean = ChartSlideSpec(
        title="Acme leads the segment with 34 units per store",
        chart={"kind": "native_chart", "chart_type": "bar",
               "categories": ["Acme", "Beta", "Gamma", "Delta"],
               "series": [{"name": "s", "values": [34, 25, 20, 15]}],
               "sort": "desc", "highlight": "Acme", "annotation": None,
               "value_suffix": ""},
    ).model_dump()

    def fake(name, schema, prompt, max_tokens=16000):
        prompts.append(prompt)
        return clean

    monkeypatch.setattr(sg, "_structured_call", fake)
    try:
        sg.generate_slide("chart_slide",
                          "Acme leads the segment on volume", "prompt", None)
    finally:
        style_priors.load_priors.cache_clear()
    assert "STYLE PRIORS" in prompts[0]
    assert "ranking_comparison" in prompts[0]


def test_judge_rubric_carries_craft_checklist(monkeypatch, tmp_path):
    from deckengine.llm import judge
    _install_priors(monkeypatch, tmp_path, PRIORS)
    try:
        text = judge._craft_checklist()
    finally:
        style_priors.load_priors.cache_clear()
    assert "craft markers" in text
    assert "so-what callout" in text


def test_no_priors_file_is_silent(monkeypatch, tmp_path):
    monkeypatch.setattr(style_priors, "PRIORS_PATH",
                        tmp_path / "missing.json")
    style_priors.load_priors.cache_clear()
    from deckengine.llm import judge
    try:
        assert judge._craft_checklist() == ""
        assert style_priors.prior_block("chart_slide", "Acme leads") == ""
    finally:
        style_priors.load_priors.cache_clear()

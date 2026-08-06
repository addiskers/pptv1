"""Multi-candidate + judge pipeline (all LLM/COM calls mocked)."""
from pathlib import Path

from deckengine.llm import spec_generator as sg
from deckengine.schema.slide_types import BulletContentSpec


def slide_a() -> dict:
    return BulletContentSpec(
        title="Metros drive 58% of demand at accessible price points",
        bullets=[{"text": "Six corridors hold **58%** of national volume"}],
    ).model_dump()


def slide_b() -> dict:
    return BulletContentSpec(
        title="Metros drive 58% of demand at accessible price points",
        bullets=[{"text": "Six corridors hold **58%** of national volume"},
                 {"text": "Corridor payback runs under **14 months**"}],
    ).model_dump()


def test_cheap_mode_single_call(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "1")
    calls = []
    monkeypatch.setattr(sg, "_structured_call",
                        lambda n, s, p, max_tokens=16000: (calls.append(p)
                                                           or slide_a()))
    sg.generate_slide_best("bullet_content", "claim", "prompt", None)
    assert len(calls) == 1


def test_identical_candidates_skip_scoring(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "2")
    monkeypatch.setattr(sg, "_structured_call",
                        lambda n, s, p, max_tokens=16000: slide_a())

    def boom(*a, **k):
        raise AssertionError("must not render identical candidates")

    monkeypatch.setattr(sg, "_render_candidate", boom)
    slide = sg.generate_slide_best("bullet_content", "claim", "prompt", None)
    assert slide.bullets[0].text.startswith("Six corridors")


def test_deterministic_winner_no_judge(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "2")
    responses = [slide_a(), slide_b()]
    monkeypatch.setattr(sg, "_structured_call",
                        lambda n, s, p, max_tokens=16000: responses.pop(0))
    scores = {"cand0": {"defects": 2, "fill": 0.5, "pptx": Path("a.pptx")},
              "cand1": {"defects": 0, "fill": 0.5, "pptx": Path("b.pptx")}}
    monkeypatch.setattr(sg, "_render_candidate",
                        lambda slide, theme, wd, tag: scores[tag])

    def no_judge(*a, **k):
        raise AssertionError("judge must not run on a clear margin")

    monkeypatch.setattr(sg, "_export_png", no_judge)
    slide = sg.generate_slide_best("bullet_content", "claim", "prompt", None)
    assert len(slide.bullets) == 2  # cand1 (fewer defects) won


def test_tie_goes_to_vision_judge_and_records_win(monkeypatch, tmp_path):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "2")
    monkeypatch.setattr(sg, "WON_DIR", tmp_path / "won")
    responses = [slide_a(), slide_b()]
    monkeypatch.setattr(sg, "_structured_call",
                        lambda n, s, p, max_tokens=16000: responses.pop(0))
    monkeypatch.setattr(
        sg, "_render_candidate",
        lambda slide, theme, wd, tag: {"defects": 0, "fill": 0.9,
                                       "pptx": Path(f"{tag}.pptx")})
    monkeypatch.setattr(sg, "_export_png",
                        lambda pptx: Path(str(pptx) + ".png"))

    import deckengine.llm.judge as judge_mod
    monkeypatch.setattr(judge_mod, "pairwise_judge",
                        lambda a, b, claim: ("B", "denser evidence"))
    slide = sg.generate_slide_best("bullet_content", "claim", "prompt", None)
    assert len(slide.bullets) == 2  # judge picked B (the runner-up)
    wins = list((tmp_path / "won").glob("bullet_content_*.json"))
    assert len(wins) == 1


def test_variant_prompt_nudges_second_candidate(monkeypatch):
    monkeypatch.setenv("DECKENGINE_CANDIDATES", "2")
    prompts = []
    responses = [slide_a(), slide_b()]

    def fake(n, s, p, max_tokens=16000):
        prompts.append(p)
        return responses.pop(0)

    monkeypatch.setattr(sg, "_structured_call", fake)
    monkeypatch.setattr(
        sg, "_render_candidate",
        lambda slide, theme, wd, tag: {"defects": 0 if tag == "cand0" else 5,
                                       "fill": 0.9, "pptx": Path("x.pptx")})
    sg.generate_slide_best("bullet_content", "claim", "prompt", None)
    assert "DIFFERENT structural approach" not in prompts[0]
    assert "DIFFERENT structural approach" in prompts[1]


def test_won_exemplar_joins_few_shots(monkeypatch, tmp_path):
    won = tmp_path / "won"
    won.mkdir()
    (won / "bullet_content_abc123.json").write_text(
        '{"slide_type": "bullet_content"}', encoding="utf-8")
    monkeypatch.setattr(sg, "WON_DIR", won)
    shot = sg._few_shot("bullet_content")
    assert "abc123" not in shot  # content, not filename
    assert '{"slide_type": "bullet_content"}' in shot

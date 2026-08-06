"""FastAPI layer: POST /generate -> job -> pptx + previews.

Auth: set DECKENGINE_API_KEY; requests must send X-API-Key. (Review finding:
never serve client-confidential decks unauthenticated.)
Run: uvicorn deckengine.api.main:app --reload
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from ..render.deck_builder import build_deck
from ..schema.slide_types import DeckSpec

from ..envfile import load_env
load_env()

app = FastAPI(title="DeckEngine", version="0.1.0")

JOBS_DIR = Path(tempfile.gettempdir()) / "deckengine_jobs"
_JOBS: dict[str, dict] = {}
_UI = Path(__file__).with_name("ui.html")
_REPO = Path(__file__).resolve().parents[2]


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return _UI.read_text(encoding="utf-8")


@app.get("/demo-spec")
def demo_spec() -> dict:
    return json.loads((_REPO / "examples" / "specs" / "agdev_demo.json")
                      .read_text(encoding="utf-8"))


@app.get("/themes")
def list_themes() -> list[dict]:
    """Enumerate available themes with swatch colors so the UI picker is
    data-driven (brand themes drop in as files, no UI change)."""
    from ..core.theme import THEMES_DIR, load_theme
    out = []
    for p in sorted(THEMES_DIR.glob("*.json")):
        try:
            t = load_theme(p.stem)
        except Exception:  # noqa: BLE001 — a malformed theme just hides
            continue
        out.append({"name": p.stem,
                    "primary": "#" + t.color_primary,
                    "primary_dark": "#" + t.color_primary_dark,
                    "accent": "#" + t.color_accent,
                    "bg": "#" + t.color_bg,
                    "ink": "#" + t.color_ink})
    return out


def _check_key(x_api_key: str | None) -> None:
    expected = os.environ.get("DECKENGINE_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(401, "invalid API key")


class GenerateFromSpec(BaseModel):
    spec: DeckSpec


class GenerateFromPrompt(BaseModel):
    prompt: str
    csv_text: str | None = None
    theme: str = "consulting_navy"
    auto_approve: bool = False  # True: skip the outline gate (CLI behavior)


class ApproveOutline(BaseModel):
    outline: dict  # (possibly edited) claim chain from /jobs/{id}


@app.post("/render")
def render_spec(req: GenerateFromSpec, background: BackgroundTasks,
                x_api_key: str | None = Header(default=None)) -> dict:
    """Deterministic path: validated spec in, pptx out."""
    _check_key(x_api_key)
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "running"}
    background.add_task(_run_render, job_id, req.spec)
    return {"job_id": job_id}


@app.post("/generate")
def generate(req: GenerateFromPrompt, background: BackgroundTasks,
             x_api_key: str | None = Header(default=None)) -> dict:
    """LLM path. Default flow: stage 1 produces a claim-chain outline for HUMAN
    APPROVAL (the highest-leverage 30 seconds in the pipeline); POST
    /jobs/{id}/approve continues to slides. auto_approve=True skips the gate."""
    _check_key(x_api_key)
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "running", "request": req.model_dump()}
    if req.auto_approve:
        background.add_task(_run_generate, job_id, req, None)
    else:
        background.add_task(_run_outline, job_id, req)
    return {"job_id": job_id}


@app.post("/jobs/{job_id}/approve")
def approve(job_id: str, req: ApproveOutline, background: BackgroundTasks,
            x_api_key: str | None = Header(default=None)) -> dict:
    _check_key(x_api_key)
    job = _JOBS.get(job_id)
    if not job or job.get("status") != "awaiting_approval":
        raise HTTPException(409, "job is not awaiting approval")
    from ..llm.story import Outline
    outline = Outline.model_validate(req.outline)
    gen_req = GenerateFromPrompt.model_validate(job["request"])
    _JOBS[job_id] = {"status": "running", "request": job["request"]}
    background.add_task(_run_generate, job_id, gen_req, outline)
    return {"job_id": job_id, "status": "running"}


@app.get("/jobs/{job_id}")
def job_status(job_id: str,
               x_api_key: str | None = Header(default=None)) -> dict:
    _check_key(x_api_key)
    job = _load_job(job_id)
    if job is None:
        raise HTTPException(404)
    return job


@app.get("/download/{job_id}")
def download(job_id: str,
             x_api_key: str | None = Header(default=None)) -> FileResponse:
    _check_key(x_api_key)
    job = _load_job(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "not ready")
    return FileResponse(job["path"], filename="deck.pptx")


@app.get("/previews/{job_id}/{n}")
def preview_png(job_id: str, n: int,
                x_api_key: str | None = Header(default=None)) -> FileResponse:
    _check_key(x_api_key)
    p = JOBS_DIR / job_id / "previews" / f"slide{n:02d}.png"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


def _run_render(job_id: str, spec: DeckSpec) -> None:
    try:
        job_dir = JOBS_DIR / job_id
        out = job_dir / "deck.pptx"
        report = build_deck(spec, out)
        previews = 0
        try:  # Windows + Office only; absence must not fail the job
            from ..render.preview import export_pngs_powerpoint
            previews = len(export_pngs_powerpoint(out, job_dir / "previews",
                                                  width=1280, height=720))
        except Exception:  # noqa: BLE001
            pass
        meta = {"status": "done", "path": str(out),
                "title": spec.meta.title, "slides": len(spec.slides),
                "warnings": report.warnings,
                "truncations": report.truncations,
                "previews": previews,
                "request": _JOBS.get(job_id, {}).get("request")}
        # persist: the spec is the source of truth; jobs survive restarts
        (job_dir / "spec.json").write_text(spec.model_dump_json(indent=2),
                                           encoding="utf-8")
        (job_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        _JOBS[job_id] = meta
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e)}


def _load_job(job_id: str) -> dict | None:
    if job_id in _JOBS:
        return _JOBS[job_id]
    meta_p = JOBS_DIR / job_id / "meta.json"
    if meta_p.is_file():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        _JOBS[job_id] = meta
        return meta
    return None


@app.get("/decks")
def list_decks(x_api_key: str | None = Header(default=None)) -> list[dict]:
    _check_key(x_api_key)
    out = []
    if JOBS_DIR.is_dir():
        for d in sorted(JOBS_DIR.iterdir(),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            meta_p = d / "meta.json"
            if meta_p.is_file():
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                out.append({"deck_id": d.name, "title": m.get("title"),
                            "slides": m.get("slides"),
                            "warnings": len(m.get("warnings", []))})
    return out[:50]


class RegenSlide(BaseModel):
    instruction: str  # "reroll slide 4 with a note"


@app.patch("/decks/{job_id}/slides/{n}")
def regen_slide(job_id: str, n: int, req: RegenSlide,
                background: BackgroundTasks,
                x_api_key: str | None = Header(default=None)) -> dict:
    """Regenerate ONE slide's spec, then re-render the whole deck (rendering
    is deterministic and takes seconds — never do in-place pptx surgery)."""
    _check_key(x_api_key)
    job = _load_job(job_id)
    spec_p = JOBS_DIR / job_id / "spec.json"
    if not job or job.get("status") != "done" or not spec_p.is_file():
        raise HTTPException(409, "deck not ready or spec missing")
    spec = DeckSpec.model_validate_json(spec_p.read_text(encoding="utf-8"))
    if not (1 <= n <= len(spec.slides)):
        raise HTTPException(404, f"deck has {len(spec.slides)} slides")
    _JOBS[job_id] = {**job, "status": "running"}
    background.add_task(_run_regen, job_id, spec, n, req.instruction,
                        job.get("request"))
    return {"job_id": job_id, "status": "running"}


def _run_regen(job_id: str, spec: DeckSpec, n: int, instruction: str,
               request: dict | None) -> None:
    try:
        from ..llm.facts import FactTable
        from ..llm.spec_generator import generate_slide
        target = spec.slides[n - 1]
        req = request or {}
        facts = (FactTable.from_csv(req["csv_text"])
                 if req.get("csv_text") else None)
        prior = [f"[{s.slide_type}] {getattr(s, 'title', s.slide_type)}"
                 for i, s in enumerate(spec.slides) if i != n - 1]
        claim = (f"{getattr(target, 'title', '')} — REVISION INSTRUCTION from "
                 f"the analyst: {instruction}")
        new_slide = generate_slide(target.slide_type, claim,
                                   req.get("prompt", spec.meta.title),
                                   facts, prior_slides=prior)
        spec.slides[n - 1] = new_slide
        _run_render(job_id, spec)
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e)}


def _run_outline(job_id: str, req: GenerateFromPrompt) -> None:
    try:
        from ..llm.facts import FactTable
        from ..llm.spec_generator import generate_outline
        facts = FactTable.from_csv(req.csv_text) if req.csv_text else None
        outline = generate_outline(req.prompt, facts)
        _JOBS[job_id].update(status="awaiting_approval",
                             outline=outline.model_dump())
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e)}


def _run_generate(job_id: str, req: GenerateFromPrompt, outline) -> None:
    try:
        from ..llm.spec_generator import generate_deck_spec
        spec = generate_deck_spec(req.prompt, csv_text=req.csv_text,
                                  theme=req.theme, outline=outline)
        _run_render(job_id, spec)
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e)}

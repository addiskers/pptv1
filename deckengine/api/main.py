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
    """LLM path: prompt (+ optional CSV) -> spec -> pptx. Requires ANTHROPIC_API_KEY."""
    _check_key(x_api_key)
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "running"}
    background.add_task(_run_generate, job_id, req)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str,
               x_api_key: str | None = Header(default=None)) -> dict:
    _check_key(x_api_key)
    if job_id not in _JOBS:
        raise HTTPException(404)
    return _JOBS[job_id]


@app.get("/download/{job_id}")
def download(job_id: str,
             x_api_key: str | None = Header(default=None)) -> FileResponse:
    _check_key(x_api_key)
    job = _JOBS.get(job_id)
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
        out = JOBS_DIR / job_id / "deck.pptx"
        report = build_deck(spec, out)
        previews = 0
        try:  # Windows + Office only; absence must not fail the job
            from ..render.preview import export_pngs_powerpoint
            previews = len(export_pngs_powerpoint(out, out.parent / "previews",
                                                  width=1280, height=720))
        except Exception:  # noqa: BLE001
            pass
        _JOBS[job_id] = {"status": "done", "path": str(out),
                         "warnings": report.warnings,
                         "truncations": report.truncations,
                         "previews": previews}
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e)}


def _run_generate(job_id: str, req: GenerateFromPrompt) -> None:
    try:
        from ..llm.spec_generator import generate_deck_spec
        spec = generate_deck_spec(req.prompt, csv_text=req.csv_text,
                                  theme=req.theme)
        _run_render(job_id, spec)
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e)}

"""FastAPI layer: POST /generate -> job -> pptx + previews.

Auth: user sessions (data/users.json, per-user deck quota — see auth.py);
X-API-Key matching DECKENGINE_API_KEY remains a service bypass, and
DECKENGINE_AUTH=0 disables auth for local development. (Review finding:
never serve client-confidential decks unauthenticated.)
Run: uvicorn deckengine.api.main:app --reload
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import (BackgroundTasks, Depends, FastAPI, File,
                     HTTPException, Request, Response, UploadFile)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ..render.deck_builder import build_deck
from ..schema.slide_types import DeckSpec
from . import auth

from ..envfile import load_env
load_env()

app = FastAPI(title="DeckEngine", version="0.1.0")

# decks are user deliverables: point DECKENGINE_JOBS_DIR at durable storage
# in production (the default tempdir is fine for local dev only)
JOBS_DIR = Path(os.environ.get("DECKENGINE_JOBS_DIR")
                or Path(tempfile.gettempdir()) / "deckengine_jobs")
_JOBS: dict[str, dict] = {}
_UI = Path(__file__).with_name("ui.html")
_LOGIN = Path(__file__).with_name("login.html")
_REPO = Path(__file__).resolve().parents[2]


def _persist(job_id: str) -> None:
    """Write the job's current state to disk. Jobs are created PERSISTED —
    a server restart must never vaporize a running job (it happened: a
    deploy restart killed a 19-minute generation the UI thought was ready)."""
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "meta.json").write_text(json.dumps(_JOBS[job_id]),
                                       encoding="utf-8")


@app.on_event("startup")
def _mark_interrupted_jobs() -> None:
    """Any job still 'running'/'awaiting_approval' on disk at startup died
    with the previous process: mark it errored (which also refunds the
    owner's quota) instead of leaving a ghost the UI polls forever."""
    if not JOBS_DIR.is_dir():
        return
    for d in JOBS_DIR.iterdir():
        meta_p = d / "meta.json"
        if not meta_p.is_file():
            continue
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if meta.get("status") in ("running", "awaiting_approval"):
            meta = {"status": "error",
                    "error": "interrupted by a server restart — please "
                             "generate again",
                    "owner": meta.get("owner")}
            meta_p.write_text(json.dumps(meta), encoding="utf-8")


@app.get("/")
def ui(request: Request):
    if auth.identity_of(request) is None:
        return RedirectResponse("/login")
    return HTMLResponse(_UI.read_text(encoding="utf-8"))


# -- auth ----------------------------------------------------------------

class OtpRequest(BaseModel):
    email: str


class OtpVerify(BaseModel):
    email: str
    code: str


@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    return _LOGIN.read_text(encoding="utf-8")


@app.post("/auth/send-otp")
def send_otp(req: OtpRequest) -> dict:
    """Send a 6-digit OTP to the given email (works for both sign-up and
    login). Returns whether the account already exists so the UI can show
    the right copy."""
    email = req.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(400, "Please enter a valid email address.")
    exists = auth.user_exists(email)
    code = auth.generate_otp(email)
    auth.send_otp_email(email, code)
    return {"ok": True, "is_new": not exists}


@app.post("/auth/verify-otp")
def verify_otp(req: OtpVerify, response: Response) -> dict:
    """Verify the OTP. Creates the account if the user is new. Sets the
    session cookie on success."""
    email = req.email.lower().strip()
    auth.verify_otp(email, req.code)
    is_new = not auth.user_exists(email)
    # create the account if it doesn't exist yet (sign-up flow)
    if is_new:
        auth.create_user(email)
    response.set_cookie(auth.SESSION_COOKIE,
                        auth.make_session(email),
                        max_age=auth.SESSION_TTL, httponly=True,
                        samesite="lax")
    return {"ok": True, "is_new": is_new}


@app.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/me")
def me(user: str = Depends(auth.current_user)) -> dict:
    if auth.is_service(user):
        return {"email": user, "quota": None, "used": 0}
    return {"email": user, "quota": auth.quota_for(user),
            "used": _decks_used(user)}


def _decks_used(email: str) -> int:
    """Deck-quota UNITS this user has consumed (running + done; errors
    refund). A variant batch's N jobs share one batch_id and count as ONE
    unit — grouping by (batch_id or job_id) is what makes that work."""
    ids = set(_JOBS)
    if JOBS_DIR.is_dir():
        ids |= {d.name for d in JOBS_DIR.iterdir()
                if (d / "meta.json").is_file()}
    units = set()
    for jid in ids:
        meta = _load_job(jid) or {}
        if meta.get("owner") == email and meta.get("status") != "error":
            units.add(meta.get("batch_id") or jid)
    return len(units)


def _check_quota(user: str) -> None:
    if auth.is_service(user):
        return
    quota = auth.quota_for(user)
    used = _decks_used(user)
    if used >= quota:
        raise HTTPException(
            403, f"Deck limit reached ({used}/{quota}). Each account can "
                 f"create {quota} presentation{'s' if quota != 1 else ''} — "
                 "contact SkyQuest to raise your limit.")


def _own_or_404(user: str, job: dict | None) -> dict:
    """Regular users only see their own jobs (legacy ownerless jobs stay
    admin/service-visible only)."""
    if job is None:
        raise HTTPException(404)
    if not auth.is_service(user) and job.get("owner") != user:
        raise HTTPException(404)
    return job


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


@app.post("/assets")
async def upload_asset(file: UploadFile = File(...),
                       user: str = Depends(auth.current_user)) -> dict:
    """Store an uploaded image (e.g. a brand logo) under assets/uploads/ and
    return its asset name to drop into a spec's meta.logo or the generate
    request. resolve_asset() finds it by that name at render time."""
    import re
    from ..core.assets import ASSETS_DIR
    raw = Path(file.filename or "logo.png").name
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw) or "logo.png"
    dest_dir = ASSETS_DIR / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / safe).write_bytes(await file.read())
    return {"asset": f"uploads/{safe}"}


class GenerateFromSpec(BaseModel):
    spec: DeckSpec


class GenerateFromPrompt(BaseModel):
    prompt: str
    csv_text: str | None = None
    theme: str = "consulting_navy"
    logo: str | None = None  # asset name from POST /assets -> meta.logo
    auto_approve: bool = False  # True: skip the outline gate (CLI behavior)
    # 'best' = multi-candidate + vision judge (EXPENSIVE: roughly 2x the
    # LLM spend of 'fast' plus vision calls); 'fast' = one candidate.
    # Default fast — cost burned a real user; 'best' is an explicit choice.
    quality: Literal["best", "fast"] = "fast"
    # id -> answer from POST /intake's questions; only the ones answered
    intake_answers: dict[str, str] | None = None
    # True: diagram slides use REAL PowerPoint SmartArt (editable via the
    # SmartArt UI; server previews show an empty frame until opened in
    # PowerPoint). Default: the engine's drawn diagram forms.
    smartart: bool = False


class IntakeRequest(BaseModel):
    prompt: str
    csv_text: str | None = None


@app.post("/intake")
def intake_questions(req: IntakeRequest,
                     user: str = Depends(auth.current_user)) -> dict:
    """Best-effort clarifying questions tailored to this brief. Never
    touches quota (creates no job) and never blocks compose: any failure
    just returns an empty list."""
    try:
        from ..llm.intake import IntakeQuestions, intake_prompt
        from ..llm.spec_generator import _structured_call, fast_model_id
        raw = _structured_call(
            "intake_questions", IntakeQuestions.model_json_schema(),
            intake_prompt(req.prompt, bool(req.csv_text)),
            max_tokens=2000, model="fast")
        return IntakeQuestions.model_validate(raw).model_dump()
    except Exception as e:  # noqa: BLE001 — best-effort, never blocks compose
        import logging
        logging.getLogger("deckengine").warning(
            "intake questions failed: %s", e)
        return {"questions": []}


def _fold_intake(prompt: str, answers: dict[str, str] | None) -> str:
    """Fold answered clarifying questions into the brief the LLM sees.
    Question ids are short human-readable slugs (e.g. 'audience',
    'decision') — good enough as labels without round-tripping the
    original question text."""
    if not answers:
        return prompt
    lines = [f"- {k.replace('_', ' ')}: {v.strip()}"
             for k, v in answers.items() if v and v.strip()]
    if not lines:
        return prompt
    return (prompt + "\n\nSTAKEHOLDER CONTEXT (from clarifying questions — "
            "honor these, they came from the person who requested this "
            "deck):\n" + "\n".join(lines))


class ApproveOutline(BaseModel):
    outline: dict  # (possibly edited) claim chain from /jobs/{id}


@app.post("/render")
def render_spec(req: GenerateFromSpec, background: BackgroundTasks,
                user: str = Depends(auth.current_user)) -> dict:
    """Deterministic path: validated spec in, pptx out."""
    _check_quota(user)
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "running", "owner": user}
    _persist(job_id)
    background.add_task(_run_render, job_id, req.spec)
    return {"job_id": job_id}


@app.post("/generate")
def generate(req: GenerateFromPrompt, background: BackgroundTasks,
             user: str = Depends(auth.current_user)) -> dict:
    """LLM path. Default flow: stage 1 produces a claim-chain outline for HUMAN
    APPROVAL (the highest-leverage 30 seconds in the pipeline); POST
    /jobs/{id}/approve continues to slides. auto_approve=True skips the gate."""
    _check_quota(user)
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "running", "owner": user,
                     "request": req.model_dump()}
    _persist(job_id)
    if req.auto_approve:
        background.add_task(_run_generate, job_id, req, None)
    else:
        background.add_task(_run_outline, job_id, req)
    return {"job_id": job_id}


class GenerateBatch(BaseModel):
    prompt: str
    csv_text: str | None = None
    theme: str = "consulting_navy"
    logo: str | None = None
    quality: Literal["best", "fast"] = "fast"
    n: int = 5
    intake_answers: dict[str, str] | None = None
    smartart: bool = False  # see GenerateFromPrompt.smartart


@app.post("/generate-batch")
def generate_batch(req: GenerateBatch, background: BackgroundTasks,
                   user: str = Depends(auth.current_user)) -> dict:
    """N variants of ONE brief — each argues via a different narrative
    flow, so they read as genuinely different decks, not N drafts of one
    idea. Charged as a SINGLE quota unit: all N jobs share a batch_id and
    _decks_used() counts distinct batch_ids, not distinct jobs."""
    _check_quota(user)
    n = max(2, min(5, req.n))
    batch_id = uuid.uuid4().hex[:12]
    job_ids = []
    for _ in range(n):
        job_id = uuid.uuid4().hex[:12]
        job_ids.append(job_id)
        _JOBS[job_id] = {"status": "running", "owner": user,
                         "batch_id": batch_id, "request": req.model_dump()}
        _persist(job_id)
    background.add_task(_run_batch, batch_id, job_ids, req)
    return {"batch_id": batch_id, "job_ids": job_ids}


@app.get("/batches/{batch_id}")
def batch_status(batch_id: str,
                 user: str = Depends(auth.current_user)) -> dict:
    variants = []
    if JOBS_DIR.is_dir():
        for d in sorted(JOBS_DIR.iterdir(), key=lambda p: p.name):
            meta_p = d / "meta.json"
            if not meta_p.is_file():
                continue
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            if m.get("batch_id") != batch_id:
                continue
            if not auth.is_service(user) and m.get("owner") != user:
                raise HTTPException(404)
            variants.append({"job_id": d.name, "status": m.get("status"),
                             "progress": m.get("progress"),
                             "title": m.get("title"),
                             "flow_id": m.get("flow_id"),
                             "angle": m.get("angle"),
                             "theme": m.get("theme"),
                             "design_language": m.get("design_language"),
                             "warnings": len(m.get("warnings", [])),
                             "similar_pairs": m.get("batch_similar_pairs")})
    if not variants:
        raise HTTPException(404)
    total = len(variants)
    done = sum(1 for v in variants if v["status"] in ("done", "error"))
    return {"batch_id": batch_id, "done": done, "total": total,
            "variants": variants}


@app.post("/jobs/{job_id}/approve")
def approve(job_id: str, req: ApproveOutline, background: BackgroundTasks,
            user: str = Depends(auth.current_user)) -> dict:
    job = _own_or_404(user, _JOBS.get(job_id))
    if job.get("status") != "awaiting_approval":
        raise HTTPException(409, "job is not awaiting approval")
    from ..llm.story import Outline
    outline = Outline.model_validate(req.outline)
    gen_req = GenerateFromPrompt.model_validate(job["request"])
    _JOBS[job_id] = {"status": "running", "owner": job.get("owner"),
                     "request": job["request"]}
    _persist(job_id)
    background.add_task(_run_generate, job_id, gen_req, outline)
    return {"job_id": job_id, "status": "running"}


@app.get("/jobs/{job_id}")
def job_status(job_id: str,
               user: str = Depends(auth.current_user)) -> dict:
    return _own_or_404(user, _load_job(job_id))


@app.get("/download/{job_id}")
def download(job_id: str,
             user: str = Depends(auth.current_user)) -> FileResponse:
    job = _own_or_404(user, _load_job(job_id))
    if job.get("status") != "done":
        raise HTTPException(404, "not ready")
    return FileResponse(job["path"], filename="deck.pptx")


@app.get("/previews/{job_id}/{n}")
def preview_png(job_id: str, n: int,
                user: str = Depends(auth.current_user)) -> FileResponse:
    _own_or_404(user, _load_job(job_id))
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
        try:  # provider seam (COM on Windows, soffice on Linux); never fails the job
            from ..render.preview_provider import get_preview_exporter
            exporter = get_preview_exporter()
            if exporter is not None:
                previews = len(exporter(out, job_dir / "previews",
                                        width=1280, height=720))
        except Exception:  # noqa: BLE001
            pass
        from ..schema.rich import plain
        meta = {"status": "done", "path": str(out),
                "title": spec.meta.title, "slides": len(spec.slides),
                "slide_titles": [plain(getattr(s, "title", "") or
                                       s.slide_type.replace("_", " "))[:120]
                                 for s in spec.slides],
                "warnings": report.warnings,
                "truncations": report.truncations,
                "previews": previews,
                "owner": _JOBS.get(job_id, {}).get("owner"),
                "request": _JOBS.get(job_id, {}).get("request")}
        # persist: the spec is the source of truth; jobs survive restarts
        (job_dir / "spec.json").write_text(spec.model_dump_json(indent=2),
                                           encoding="utf-8")
        (job_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        _JOBS[job_id] = meta
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e),
                         "owner": _JOBS.get(job_id, {}).get("owner")}
        _persist(job_id)


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
def list_decks(user: str = Depends(auth.current_user)) -> list[dict]:
    out = []
    if JOBS_DIR.is_dir():
        for d in sorted(JOBS_DIR.iterdir(),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            meta_p = d / "meta.json"
            if meta_p.is_file():
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                if not auth.is_service(user) and m.get("owner") != user:
                    continue  # users only see their own decks
                out.append({"deck_id": d.name, "title": m.get("title"),
                            "slides": m.get("slides"),
                            "warnings": len(m.get("warnings", []))})
    return out[:50]


class RegenSlide(BaseModel):
    instruction: str  # "reroll slide 4 with a note"


@app.patch("/decks/{job_id}/slides/{n}")
def regen_slide(job_id: str, n: int, req: RegenSlide,
                background: BackgroundTasks,
                user: str = Depends(auth.current_user)) -> dict:
    """Regenerate ONE slide's spec, then re-render the whole deck (rendering
    is deterministic and takes seconds — never do in-place pptx surgery).
    Reworking an existing deck does NOT consume quota."""
    job = _own_or_404(user, _load_job(job_id))
    spec_p = JOBS_DIR / job_id / "spec.json"
    if job.get("status") != "done" or not spec_p.is_file():
        raise HTTPException(409, "deck not ready or spec missing")
    spec = DeckSpec.model_validate_json(spec_p.read_text(encoding="utf-8"))
    if not (1 <= n <= len(spec.slides)):
        raise HTTPException(404, f"deck has {len(spec.slides)} slides")
    # regen_slide lets the UI show a per-slide busy state while the rest of
    # the deck stays interactive
    _JOBS[job_id] = {**job, "status": "running", "regen_slide": n}
    _persist(job_id)
    background.add_task(_run_regen, job_id, spec, n, req.instruction,
                        job.get("request"))
    return {"job_id": job_id, "status": "running", "regen_slide": n}


def _run_regen(job_id: str, spec: DeckSpec, n: int, instruction: str,
               request: dict | None) -> None:
    try:
        from ..llm.facts import FactTable
        from ..llm.spec_generator import generate_slide_best
        target = spec.slides[n - 1]
        req = request or {}
        facts = (FactTable.from_csv(req["csv_text"])
                 if req.get("csv_text") else None)
        prior = [f"[{s.slide_type}] {getattr(s, 'title', s.slide_type)}"
                 for i, s in enumerate(spec.slides) if i != n - 1]
        claim = (f"{getattr(target, 'title', '')} — REVISION INSTRUCTION from "
                 f"the analyst: {instruction}")
        # multi-candidate + judge: this is the ONE slide the user is
        # actively watching — worth the extra ~30s
        new_slide = generate_slide_best(target.slide_type, claim,
                                        req.get("prompt", spec.meta.title),
                                        facts, prior_slides=prior,
                                        theme=req.get("theme",
                                                      "consulting_navy"))
        spec.slides[n - 1] = new_slide
        _run_render(job_id, spec)
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e),
                         "owner": _JOBS.get(job_id, {}).get("owner")}
        _persist(job_id)


def _run_outline(job_id: str, req: GenerateFromPrompt) -> None:
    try:
        from ..llm.facts import FactTable
        from ..llm.spec_generator import generate_outline
        facts = FactTable.from_csv(req.csv_text) if req.csv_text else None
        outline = generate_outline(
            _fold_intake(req.prompt, req.intake_answers), facts)
        _JOBS[job_id].update(status="awaiting_approval",
                             outline=outline.model_dump())
        _persist(job_id)
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e),
                         "owner": _JOBS.get(job_id, {}).get("owner")}
        _persist(job_id)


def _run_generate(job_id: str, req: GenerateFromPrompt, outline) -> None:
    try:
        from ..llm.spec_generator import generate_deck_spec
        from ..schema.slide_types import DeckMeta
        meta = (DeckMeta(title=req.prompt[:150], logo=req.logo)
                if req.logo else None)

        def _progress(done: int, total: int, stage: str) -> None:
            # visible progress ("Designing slide 7/14") — persisted so a
            # page reload keeps the counter
            job = _JOBS.get(job_id)
            if job is not None and job.get("status") == "running":
                job["progress"] = {"done": done, "total": total,
                                   "stage": stage}
                _persist(job_id)

        from ..llm.variants import SMARTART_DIRECTIVE
        spec = generate_deck_spec(
            _fold_intake(req.prompt, req.intake_answers), csv_text=req.csv_text,
            theme=req.theme, meta=meta, outline=outline,
            quality=req.quality, progress_cb=_progress,
            design_directive=SMARTART_DIRECTIVE if req.smartart else None)
        _run_render(job_id, spec)
    except Exception as e:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(e),
                         "owner": _JOBS.get(job_id, {}).get("owner")}
        _persist(job_id)


# ---------------------------------------------------------------------------
# variant batch: N decks from one brief, one quota unit
# ---------------------------------------------------------------------------

def _batch_parallel() -> int:
    """Outer concurrency across variants — kept low because each variant
    already runs its own internal slide-wave parallelism (T5.6); 2 outer
    x 4 inner keeps total concurrent LLM calls sane."""
    try:
        return max(1, min(5, int(
            os.environ.get("DECKENGINE_BATCH_PARALLEL", "2"))))
    except ValueError:
        return 2


# visual rotation for the variant batch, most-distinct-first; the user's
# chosen theme always leads, skyquest_brand joins only when chosen
_THEME_ROTATION = ["consulting_navy", "consulting_paper", "midnight_cyan",
                   "emerald_gold", "burgundy_cream", "graphite_amber",
                   "forest_stone", "indigo_gold", "teal_coral",
                   "crimson_charcoal"]


def _variant_themes(chosen: str, n: int) -> list[str]:
    """n DISTINCT themes, the user's choice first — variants must look
    different at a glance, not just argue differently."""
    rest = [t for t in _THEME_ROTATION if t != chosen]
    return ([chosen] + rest + [chosen] * n)[:n]   # pad defensively


def _run_batch(batch_id: str, job_ids: list[str], req: GenerateBatch) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from ..llm.facts import FactTable
    from ..llm.spec_generator import (_structured_call, fast_model_id,
                                      generate_deck_spec, generate_outline)
    from ..llm.variants import (DeckAngles, angle_prompt, design_directive,
                                fallback_angles)
    from ..schema.slide_types import DeckMeta

    prompt = _fold_intake(req.prompt, req.intake_answers)
    facts = FactTable.from_csv(req.csv_text) if req.csv_text else None
    n = len(job_ids)
    try:
        raw = _structured_call(
            "deck_angles", DeckAngles.model_json_schema(),
            angle_prompt(prompt, n), max_tokens=4000, model="fast")
        angles = DeckAngles.model_validate(raw).angles
        if len(angles) != n or len({a.flow_id for a in angles}) != n:
            angles = fallback_angles(n)
    except Exception:  # noqa: BLE001 — the diversity floor never depends on this
        angles = fallback_angles(n)
    # design languages must be distinct too; if the model repeated any,
    # take the whole assignment from the deterministic rotation
    if len({a.design_language for a in angles}) != n:
        fb = fallback_angles(n)
        for a, f in zip(angles, fb):
            a.design_language = f.design_language

    themes = _variant_themes(req.theme, n)
    # covers rotate composition too — five decks must not OPEN identically
    cover_styles = ["dark_hero", "split_panel", "light_minimal",
                    "band_statement"]
    governing: dict[str, str] = {}
    lock = threading.Lock()

    def _one(job_id: str, angle, theme: str, cover_style: str) -> None:
        def _tag(job: dict) -> dict:
            job["batch_id"] = batch_id
            job["flow_id"] = angle.flow_id
            job["angle"] = angle.angle
            job["design_language"] = angle.design_language
            job["theme"] = theme
            return job

        try:
            outline = generate_outline(
                prompt, facts, forced_flow=angle.flow_id,
                angle_hint=angle.emphasis_seed or angle.angle)
            with lock:
                governing[job_id] = outline.governing_thought
            meta = (DeckMeta(title=req.prompt[:150], logo=req.logo)
                    if req.logo else None)

            def _progress(done: int, total: int, stage: str) -> None:
                job = _JOBS.get(job_id)
                if job is not None and job.get("status") == "running":
                    job["progress"] = {"done": done, "total": total,
                                       "stage": stage}
                    _tag(job)
                    _persist(job_id)

            from ..llm.variants import SMARTART_DIRECTIVE
            dd = design_directive(angle.design_language)
            if req.smartart:
                dd = f"{dd} {SMARTART_DIRECTIVE}" if dd \
                    else SMARTART_DIRECTIVE
            spec = generate_deck_spec(
                prompt, csv_text=req.csv_text, theme=theme, meta=meta,
                outline=outline, quality=req.quality, progress_cb=_progress,
                design_directive=dd)
            for s in spec.slides:
                if s.slide_type == "title":
                    s.style = cover_style   # deterministic, not model luck
        except Exception as e:  # noqa: BLE001 — one bad variant must not sink the batch
            _JOBS[job_id] = _tag(
                {"status": "error", "error": str(e),
                 "owner": _JOBS.get(job_id, {}).get("owner")})
            _persist(job_id)
            return
        _run_render(job_id, spec)          # replaces _JOBS[job_id] wholesale
        job = _JOBS.get(job_id)             # so batch tags are re-applied after
        if job is not None:
            _tag(job)
            _persist(job_id)

    with ThreadPoolExecutor(max_workers=_batch_parallel()) as pool:
        list(pool.map(lambda t: _one(*t),
                      zip(job_ids, angles, themes,
                          (cover_styles[i % len(cover_styles)]
                           for i in range(n)))))

    _tag_batch_diversity(batch_id, job_ids, governing)


def _tag_batch_diversity(batch_id: str, job_ids: list[str],
                         governing: dict[str, str]) -> None:
    """QA signal, not an auto-fix (T5.6's within-deck sweeps regen a
    slide in seconds; regenerating a whole duplicate DECK costs minutes,
    too expensive to trigger speculatively). Flags pairs whose governing
    thought still reads alike despite the forced-flow diversity floor."""
    from ..llm.spec_generator import _dupe_pairs
    ordered = [jid for jid in job_ids if jid in governing]
    if len(ordered) < 2:
        return
    pairs = _dupe_pairs([governing[jid] for jid in ordered])
    if not pairs:
        return
    tagged = [[ordered[i], ordered[j]] for i, j in pairs]
    for jid in job_ids:
        job = _JOBS.get(jid) or _load_job(jid)
        if job is not None:
            job["batch_similar_pairs"] = tagged
            _JOBS[jid] = job
            _persist(jid)

"""FastAPI app: the endpoints in MVP.md section 6.5.

Run:  uv run uvicorn app.main:app --port 8000 --reload
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app import copy as copy_text
from app import data
from app import experiment
from app import participants as explore
from app.config import settings
from app.demo_data import DEMO_PATIENT_ID
from app.jobs import jobs
from app.runner import get_model, model_is_loaded, weights_present
from app.schemas import (
    Cohort,
    Health,
    Outcome,
    ParticipantDetail,
    ParticipantPage,
    ParticipantResults,
    ParticipantRuns,
    PersonCard,
    RiskResult,
    RunRequest,
    RunStarted,
    TrajectoryGuide,
)
from app.store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    jobs.start(asyncio.get_running_loop())
    if settings.eager_model and weights_present():
        # Load the ensemble off the event loop so /api/health answers at once.
        asyncio.get_running_loop().run_in_executor(None, get_model)
    yield
    jobs.shutdown()


app = FastAPI(
    title="CTscannr",
    summary="Runs the real Sybil model on one de-identified NLST chest CT at a time.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def _candidate_or_404(patient_id: str) -> dict:
    if patient_id == DEMO_PATIENT_ID:
        return dict(data.DEMO_CANDIDATE)
    candidate = data.get_candidate(patient_id)
    if candidate is None:
        raise HTTPException(404, f"No candidate {patient_id}")
    return candidate


# ---------------------------------------------------------------------------
@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health(
        status="ok",
        model_loaded=model_is_loaded(),
        model_name=settings.model_name,
        device=settings.device,
        threads=settings.threads,
        weights_present=weights_present(),
        candidates=data.candidate_stats(),
        cache=store.stats(),
        jobs=jobs.stats(),
        published_metrics_url="https://ascopubs.org/doi/10.1200/JCO.22.01345",
    )


@app.get("/api/patients/random", response_model=PersonCard)
def random_patient(
    mode: str = Query("curated", pattern="^(curated|live)$"),
    exclude: Optional[str] = None,
) -> PersonCard:
    skip = [p for p in (exclude or "").split(",") if p]
    if mode == "curated":
        patient_id = data.pick_curated(exclude=skip)
        if patient_id is None:
            raise HTTPException(
                503,
                "No prepared people yet. Run: uv run python scripts/prepare_pool.py "
                "--pool 16 --reference 12",
            )
    else:
        if not data.have_candidates():
            raise HTTPException(503, "No candidates.parquet yet. Run scripts/build_candidates.py")
        patient_id = data.pick_live(exclude=skip)
        if patient_id is None:
            raise HTTPException(503, "No unused candidates left.")
    card = data.person_card(_candidate_or_404(patient_id))
    card["mode"] = mode
    return PersonCard(**card)


@app.get("/api/patients/{patient_id}", response_model=PersonCard)
def patient(patient_id: str) -> PersonCard:
    return PersonCard(**data.person_card(_candidate_or_404(patient_id)))


@app.post("/api/patients/{patient_id}/run", response_model=RunStarted)
def run_patient(patient_id: str) -> RunStarted:
    _candidate_or_404(patient_id)
    if store.is_ready(patient_id):
        store.touch(patient_id)
        return RunStarted(patient_id=patient_id, ready=True, state="done")
    if not weights_present():
        raise HTTPException(
            503,
            "Sybil's weights are not downloaded yet (~700 MB). Run: "
            "uv run python scripts/smoke_test.py",
        )
    job = jobs.submit(patient_id)
    return RunStarted(job_id=job.id, patient_id=patient_id, ready=False, state=job.state)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jobs.job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return job.as_dict()


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> EventSourceResponse:
    if jobs.job(job_id) is None:
        raise HTTPException(404, "Unknown job")
    return EventSourceResponse(jobs.stream(job_id))


@app.get("/api/patients/{patient_id}/result", response_model=RiskResult)
def patient_result(patient_id: str) -> RiskResult:
    result = store.result(patient_id)
    if result is None:
        raise HTTPException(404, "Not run yet")
    store.touch(patient_id)
    risks = result["risk_by_year"]
    reference = data.reference_curve()
    band = data.risk_band(risks[-1], reference)
    return RiskResult(
        patient_id=patient_id,
        risk_by_year=risks,
        risk_pct_by_year=[round(r * 100, 1) for r in risks],
        headline_pct=round(risks[-1] * 100, 1),
        people_in_100=copy_text.people_in_100(risks[-1]),
        raw_mean=result.get("raw_mean"),
        raw_per_model=result.get("raw_per_model"),
        n_slices=result["n_slices"],
        width=result["width"],
        height=result["height"],
        slice_importance=result["slice_importance"],
        hotspot_slice=result["hotspot_slice"],
        coronal_size=result.get("coronal_size", [0, 0]),
        geometry=result.get("geometry", {}),
        timings=result.get("timings", {}),
        model=result.get("model", {}),
        reference=reference,
        band=band,
        created_at=result.get("created_at"),
    )


@app.get("/api/patients/{patient_id}/outcome", response_model=Outcome)
def patient_outcome(patient_id: str) -> Outcome:
    outcome = store.outcome(patient_id)
    if outcome is None:
        raise HTTPException(404, "Not run yet — the reveal comes after the prediction")
    result = store.result(patient_id) or {}
    reference = data.reference_curve()
    band = data.risk_band(result.get("risk_by_year", [0])[-1], reference) if result else None
    text = copy_text.reveal(outcome, result, band)
    return Outcome(**{**outcome, **text})


@app.get("/api/patients/{patient_id}/slices/{index}.webp")
def slice_image(patient_id: str, index: int) -> FileResponse:
    path = store.slice_path(patient_id, index)
    if not path.exists():
        raise HTTPException(404, "No such slice")
    return FileResponse(path, media_type="image/webp", headers=IMMUTABLE)


@app.get("/api/patients/{patient_id}/overlay/{index}.webp")
def overlay_image(patient_id: str, index: int) -> FileResponse:
    path = store.overlay_path(patient_id, index)
    if not path.exists():
        raise HTTPException(404, "No such overlay")
    return FileResponse(path, media_type="image/webp", headers=IMMUTABLE)


@app.get("/api/patients/{patient_id}/coronal.webp")
def coronal_image(patient_id: str) -> FileResponse:
    path = store.coronal_path(patient_id)
    if not path.exists():
        raise HTTPException(404, "No coronal map")
    return FileResponse(path, media_type="image/webp", headers=IMMUTABLE)


@app.get("/api/cohort", response_model=Cohort)
def cohort() -> Cohort:
    return Cohort(
        people=data.cohort(),
        caveat=copy_text.TRAINING_CAVEAT + " " + copy_text.POOL_CAVEAT,
        published=copy_text.PUBLISHED_METRICS,
    )


# --- Explore: participants and their screening rounds ----------------------
def _need_participants() -> None:
    if not explore.have_participants():
        raise HTTPException(
            503,
            "No participants.parquet yet. Run: uv run python scripts/build_candidates.py",
        )


def _explore(call, *args, **kwargs):
    _need_participants()
    try:
        return call(*args, **kwargs)
    except explore.UnknownParticipant as exc:
        raise HTTPException(404, f"No participant {exc.args[0]}") from exc
    except explore.BadRequest as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/participants", response_model=ParticipantPage)
def search_participants(
    q: Optional[str] = Query(None, description="participant id prefix"),
    sex: Optional[str] = None,
    smoking: Optional[str] = None,
    race: Optional[str] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    rounds_min: Optional[int] = Query(None, ge=1, le=3, description="runnable rounds"),
    manufacturer: Optional[str] = None,
    diagnosed: Optional[bool] = Query(None, description="not allowed when blind"),
    has_results: Optional[bool] = None,
    sort: str = Query("id", description="id, age, rounds, results or dx; prefix - to flip"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    blind: bool = False,
) -> ParticipantPage:
    filters = explore.Filters(q=q, sex=sex, smoking=smoking, race=race, age_min=age_min,
                              age_max=age_max, rounds_min=rounds_min,
                              manufacturer=manufacturer, diagnosed=diagnosed,
                              has_results=has_results)
    return ParticipantPage(**_explore(explore.search, filters, sort=sort, page=page,
                                      page_size=page_size, blind=blind))


@app.get("/api/participants/{nlst_pid}", response_model=ParticipantDetail)
def participant(nlst_pid: str, blind: bool = False) -> ParticipantDetail:
    return ParticipantDetail(**_explore(explore.detail, nlst_pid, blind=blind))


@app.post("/api/participants/{nlst_pid}/runs", response_model=ParticipantRuns)
def run_participant(nlst_pid: str, request: Optional[RunRequest] = None) -> ParticipantRuns:
    _need_participants()
    if not weights_present():
        raise HTTPException(
            503,
            "Sybil's weights are not downloaded yet (~700 MB). Run: "
            "uv run python scripts/smoke_test.py",
        )
    exam_ids = request.exam_ids if request else None
    runs = _explore(explore.run, nlst_pid, exam_ids)
    return ParticipantRuns(nlst_pid=nlst_pid, runs=runs)


@app.get("/api/participants/{nlst_pid}/results", response_model=ParticipantResults)
def participant_results(nlst_pid: str, blind: bool = False) -> ParticipantResults:
    return ParticipantResults(**_explore(explore.results, nlst_pid, blind=blind))


@app.get("/api/participants/{nlst_pid}/export.csv", response_class=PlainTextResponse)
def participant_export(nlst_pid: str, blind: bool = False) -> PlainTextResponse:
    body = _explore(explore.export_csv, nlst_pid, blind=blind)
    return PlainTextResponse(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sybil_{nlst_pid}.csv"'},
    )



# --- Experiment: T0 + T1 -> T2 on one participant ----------------------------
@app.get("/api/experiments/trajectory/{nlst_pid}", response_model=TrajectoryGuide)
def trajectory_guide(nlst_pid: str) -> TrajectoryGuide:
    try:
        return TrajectoryGuide(**_explore(experiment.guide, nlst_pid))
    except experiment.NotReady as exc:
        raise HTTPException(409, str(exc)) from exc

# --- serve the built frontend, if there is one ------------------------------
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")

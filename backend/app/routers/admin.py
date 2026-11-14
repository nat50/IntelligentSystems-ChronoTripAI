"""FR-06: data overview, training jobs, model versions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import orm
from ..config import get_settings
from ..db import get_session
from ..schemas import (
    AdminOverview, BenchmarkOut, CrawlStatus, DatasetStatus, DataOverview, ExplorerPage, ImpactOut, JobOut, ModelCard,
    ModelDetail, ModelKey, ModelTrainIn, OptimizerOut, OptimizerSettings, PlaceQuality, TrainRequest, VersionOut,
)
from ..services import console, dataset, optimizer, training
from ..services.versions import activate
from .places import require_version


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    token = get_settings().admin_token
    if token and x_admin_token != token:
        raise HTTPException(401, "Admin token required")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/overview", response_model=AdminOverview)
def overview(s: SessionDep):
    stats = s.scalars(select(orm.CountryStat).order_by(orm.CountryStat.checkins.desc())).all()
    versions = s.scalars(select(orm.ModelVersion).order_by(orm.ModelVersion.created_at.desc())).all()
    job = s.scalar(select(orm.TrainingJob).order_by(orm.TrainingJob.id.desc()))
    return AdminOverview(
        country_stats=stats,
        versions=versions,
        job=job,
        dataset_found=training.dataset_found(),
        raw_dir=str(get_settings().raw_dir),
    )


@router.post("/train", response_model=JobOut, status_code=202)
def train(body: TrainRequest):
    try:
        return training.start(body.source)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=JobOut)
def job(s: SessionDep, job_id: int):
    j = s.get(orm.TrainingJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    return j


@router.get("/dataset", response_model=DatasetStatus)
def dataset_status():
    return dataset.status()


@router.post("/dataset/download", response_model=DatasetStatus, status_code=202)
def dataset_download():
    try:
        return dataset.start()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/versions/{version}/activate", response_model=VersionOut)
def activate_version(s: SessionDep, version: str):
    try:
        return activate(s, version)
    except KeyError as exc:
        raise HTTPException(404, "Version not found") from exc


# --------------------------------------------------------------------------- #
# D1 · Data
# --------------------------------------------------------------------------- #
@router.get("/data", response_model=DataOverview)
def data(s: SessionDep):
    return console.data_overview(s)


@router.get("/hours", response_model=CrawlStatus)
def hours_status():
    return console.crawl_status()


@router.post("/hours/crawl", response_model=CrawlStatus, status_code=202)
def hours_crawl():
    """Crawl opening hours from OpenStreetMap again (D1 "Re-crawl"). Train a new version to use them."""
    try:
        return console.start_crawl()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


# --------------------------------------------------------------------------- #
# D2 · Place explorer
# --------------------------------------------------------------------------- #
@router.get("/places", response_model=ExplorerPage)
def explorer_places(
    s: SessionDep,
    city: str,
    q: Annotated[str | None, Query(max_length=80)] = None,
    quality: PlaceQuality | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return console.explorer(s, require_version(s), city, q, quality, limit, offset)


# --------------------------------------------------------------------------- #
# D3 · Models
# --------------------------------------------------------------------------- #
@router.get("/models", response_model=list[ModelCard])
def models(s: SessionDep):
    return [console.model_card(s, m) for m in ("m1", "m2", "m3")]


@router.get("/models/{model}", response_model=ModelDetail)
def model_detail(s: SessionDep, model: ModelKey):
    return console.model_detail(s, model)


@router.post("/models/{model}/train", response_model=JobOut, status_code=202)
def train_model(model: ModelKey, body: ModelTrainIn):
    """Train one model with the given settings on the active version's data ("Start training").
    The two other models are copied from the active version; the result is not activated."""
    try:
        return training.start_model(model, body.settings)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/models/{model}/versions/{version}/impact", response_model=ImpactOut)
def model_impact(s: SessionDep, model: ModelKey, version: str):
    """D3 "Before you activate": how much the estimates shown to travelers would change."""
    try:
        return console.impact(s, model, version)
    except KeyError as exc:
        raise HTTPException(404, "Version not found") from exc
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/models/{model}/versions/{version}/activate", response_model=JobOut, status_code=202)
def activate_model(model: ModelKey, version: str):
    """Use this model from `version`, keep the other two ("Activate" / "Roll back"). Builds and
    activates a version holding that combination, or activates one that already exists."""
    try:
        return training.start_compose(model, version)
    except KeyError as exc:
        raise HTTPException(404, "Version not found") from exc
    except (LookupError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


# --------------------------------------------------------------------------- #
# D4 · Optimizer
# --------------------------------------------------------------------------- #
@router.get("/optimizer", response_model=OptimizerOut)
def optimizer_state(s: SessionDep):
    active, updated = optimizer.active_settings(s)
    last = s.scalar(select(orm.Benchmark).order_by(orm.Benchmark.id.desc()))
    return OptimizerOut(active=active, updated_at=updated, last_benchmark=optimizer.benchmark_out(last) if last else None)


@router.post("/optimizer/benchmark", response_model=BenchmarkOut, status_code=202)
def run_benchmark(s: SessionDep, body: OptimizerSettings):
    try:
        return optimizer.benchmark_out(optimizer.start_benchmark(s, body))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/optimizer/benchmarks/{bench_id}", response_model=BenchmarkOut)
def benchmark(s: SessionDep, bench_id: int):
    row = s.get(orm.Benchmark, bench_id)
    if row is None:
        raise HTTPException(404, "Benchmark not found")
    return optimizer.benchmark_out(row)


@router.post("/optimizer/apply", response_model=OptimizerOut)
def apply_optimizer(s: SessionDep, body: OptimizerSettings):
    """D4 "Apply to planner": every optimization from now on uses these settings."""
    optimizer.apply(s, body)
    return optimizer_state(s)

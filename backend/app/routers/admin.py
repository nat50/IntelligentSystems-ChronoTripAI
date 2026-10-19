"""FR-06: data overview, training jobs, model versions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import orm
from ..config import get_settings
from ..db import get_session
from ..schemas import AdminOverview, DatasetStatus, JobOut, TrainRequest, VersionOut
from ..services import dataset, training
from ..services.versions import activate


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

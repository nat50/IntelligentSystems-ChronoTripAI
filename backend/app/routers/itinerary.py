"""FR-02, FR-04, FR-05: configure a trip and optimise it (locks + re-optimise).

POST /optimize answers when the plan is ready. The job endpoints do the same in
the background, for the Figma T3 "Building your itinerary..." dialog: poll the job
for the generation count and the best plan so far, or cancel it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import orm
from ..db import get_session
from ..schemas import ItineraryOut, OptimizeJobOut, OptimizeRequest
from ..services import optimizer
from ..services.planner import optimize
from .places import require_version

router = APIRouter(prefix="/api/itinerary", tags=["itinerary"])
SessionDep = Annotated[Session, Depends(get_session)]


def load_places(s: Session, req: OptimizeRequest) -> list[orm.Place]:
    v = require_version(s)
    rows = s.scalars(select(orm.Place).where(orm.Place.version == v, orm.Place.id.in_(req.place_ids))).all()
    by_id = {p.id: p for p in rows}
    missing = [pid for pid in req.place_ids if pid not in by_id]
    if missing:
        raise HTTPException(409, f"Places not in the active model version: {missing}. Pick them again.")
    if any(p.city != req.city for p in rows):
        raise HTTPException(422, "All places must be in the selected city")
    return [by_id[pid] for pid in req.place_ids]


@router.post("/optimize", response_model=ItineraryOut)
async def optimize_route(req: OptimizeRequest, s: SessionDep):
    places = load_places(s, req)
    settings, _ = optimizer.active_settings(s)
    try:
        return await run_in_threadpool(optimize, req, places, settings)
    except ValueError as exc:  # e.g. every selected place is closed on the trip days
        raise HTTPException(422, str(exc)) from exc


@router.post("/jobs", response_model=OptimizeJobOut, status_code=202)
def start_job(req: OptimizeRequest, s: SessionDep):
    places = load_places(s, req)
    settings, _ = optimizer.active_settings(s)
    return optimizer.start_job(req, places, settings)


@router.get("/jobs/{job_id}", response_model=OptimizeJobOut)
def job(job_id: str):
    out = optimizer.get_job(job_id)
    if out is None:
        raise HTTPException(404, "Job not found (jobs are kept in memory and forgotten on restart)")
    return out


@router.delete("/jobs/{job_id}", response_model=OptimizeJobOut)
def cancel_job(job_id: str):
    out = optimizer.cancel_job(job_id)
    if out is None:
        raise HTTPException(404, "Job not found")
    return out

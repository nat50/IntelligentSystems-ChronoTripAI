"""FR-02, FR-04, FR-05: configure a trip and optimise it (locks + re-optimise)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import orm
from ..db import get_session
from ..schemas import ItineraryOut, OptimizeRequest
from ..services.planner import optimize
from .places import require_version

router = APIRouter(prefix="/api/itinerary", tags=["itinerary"])


@router.post("/optimize", response_model=ItineraryOut)
async def optimize_route(req: OptimizeRequest, s: Annotated[Session, Depends(get_session)]):
    v = require_version(s)
    rows = s.scalars(select(orm.Place).where(orm.Place.version == v, orm.Place.id.in_(req.place_ids))).all()
    by_id = {p.id: p for p in rows}
    missing = [pid for pid in req.place_ids if pid not in by_id]
    if missing:
        raise HTTPException(409, f"Places not in the active model version: {missing}. Pick them again.")
    if any(p.city != req.city for p in rows):
        raise HTTPException(422, "All places must be in the selected city")
    places = [by_id[pid] for pid in req.place_ids]
    try:
        return await run_in_threadpool(optimize, req, places)
    except ValueError as exc:  # e.g. every selected place is closed on the trip days
        raise HTTPException(422, str(exc)) from exc

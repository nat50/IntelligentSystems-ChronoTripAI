"""FR-01 (pick places) and FR-03 (predicted attributes)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ml.categories import labels_of_interest
from ml.geo import CITIES, DEFAULT_STAY, SUPPORTED_CITIES

from .. import orm
from ..db import get_session
from ..schemas import CityOut, Interest, PlaceDetail, PlaceOut
from ..services.quality import place_quality, search_filter
from ..services.versions import active_version

router = APIRouter(prefix="/api", tags=["places"])
SessionDep = Annotated[Session, Depends(get_session)]


def require_version(s: Session) -> str:
    v = active_version(s)
    if v is None:
        raise HTTPException(503, "No model version is active yet. Train one on the admin screen.")
    return v


@router.get("/cities", response_model=list[CityOut])
def cities(s: SessionDep):
    v = active_version(s)
    counts = dict(
        s.execute(select(orm.Place.city, func.count()).where(orm.Place.version == v).group_by(orm.Place.city)).all()
    ) if v else {}
    out = []
    for name, _, lat, lon in CITIES:
        if name in SUPPORTED_CITIES:
            slat, slon, label = DEFAULT_STAY[name]
            out.append(CityOut(name=name, lat=lat, lon=lon, stay={"lat": slat, "lon": slon, "label": label}, places=counts.get(name, 0)))
    return out


@router.get("/places", response_model=list[PlaceOut])
def places(
    s: SessionDep,
    city: str,
    bbox: Annotated[str | None, Query(description="minLon,minLat,maxLon,maxLat")] = None,
    group: str | None = None,
    interest: Annotated[list[Interest] | None, Query(description="Figma interest chips; repeat for several")] = None,
    q: Annotated[str | None, Query(max_length=80, description="search text: name, area, category or id")] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
):
    v = require_version(s)
    query = select(orm.Place).where(orm.Place.version == v, orm.Place.city == city)
    if interest:
        labels = [label for i in interest for label in labels_of_interest(i)]
        query = query.where(orm.Place.label.in_(labels))
    if q and q.strip():
        query = query.where(search_filter(q))
    return _places(s, query, bbox, group, limit)


def _places(s: Session, q, bbox: str | None, group: str | None, limit: int):
    if bbox:
        try:
            x0, y0, x1, y1 = (float(x) for x in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(422, "bbox must be minLon,minLat,maxLon,maxLat") from exc
        q = q.where(orm.Place.lon.between(x0, x1), orm.Place.lat.between(y0, y1))
    if group:
        q = q.where(orm.Place.group == group)
    return s.scalars(q.order_by(orm.Place.score.desc()).limit(limit)).all()


@router.get("/places/suggest", response_model=list[PlaceOut])
def suggest(
    s: SessionDep,
    city: str,
    limit: Annotated[int, Query(ge=1, le=30)] = 8,
    interest: Annotated[list[Interest] | None, Query(description="T1 interests; food is always kept for meals")] = None,
):
    """Automatic suggestions: the highest S_i, kept varied — at least two food places
    for meals, at most two of a kind and one nightlife spot."""
    v = require_version(s)
    ranked: list[orm.Place] = []
    for wanted in (["high"], ["medium", "low"]):  # less certain places only when the sure ones run out
        if len(ranked) < limit:
            q = select(orm.Place).where(orm.Place.version == v, orm.Place.city == city, orm.Place.confidence.in_(wanted))
            if interest:
                labels = [label for i in {*interest, "food"} for label in labels_of_interest(i)]
                q = q.where(orm.Place.label.in_(labels))
            ranked += s.scalars(q.order_by(orm.Place.score.desc(), orm.Place.n_checkins.desc()).limit(400)).all()
    caps = {"nightlife": 0 if interest and "nightlife" not in interest else 1}
    picked: list[orm.Place] = []
    per_label: dict[str, int] = {}
    per_group: dict[str, int] = {}

    def take(p: orm.Place) -> bool:
        if per_label.get(p.label, 0) >= 2 or per_group.get(p.group, 0) >= caps.get(p.group, max(3, limit // 3)):
            return False
        picked.append(p)
        per_label[p.label] = per_label.get(p.label, 0) + 1
        per_group[p.group] = per_group.get(p.group, 0) + 1
        return True

    for p in ranked:  # two meals first
        if p.group == "food" and per_group.get("food", 0) < 2:
            take(p)
    for p in ranked:
        if len(picked) >= limit:
            break
        if p not in picked:
            take(p)
    for p in ranked:  # categories ran out: fill up regardless of variety
        if len(picked) >= limit:
            break
        if p not in picked:
            picked.append(p)
    return sorted(picked, key=lambda p: -p.score)


@router.get("/places/{place_id}", response_model=PlaceDetail)
def place(s: SessionDep, place_id: int):
    v = require_version(s)
    p = s.scalar(select(orm.Place).where(orm.Place.id == place_id, orm.Place.version == v))
    if p is None:
        raise HTTPException(404, "Place not found")
    out = PlaceDetail.model_validate(p)
    mv = s.get(orm.ModelVersion, v)
    out.model_versions = {m: (mv.components or {}).get(m, v) for m in ("m1", "m2", "m3")} if mv else {}
    out.quality = place_quality(p)
    return out

"""Data-quality label of a place (Figma D2 list: Good / Low data / Missing hours)."""

from __future__ import annotations

from sqlalchemy import and_, or_

from .. import orm

LOW_DATA_CHECKINS = 10  # same cut as the "0-9" bucket of the model metrics


def place_quality(p: orm.Place) -> str:
    """missing_hours: no real opening hours and the estimate from check-ins is not reliable.
    low_data: fewer than 10 check-ins, so every estimate leans on the category / area priors."""
    if p.hours_source != "crawl" and p.confidence != "high":
        return "missing_hours"
    if p.n_checkins < LOW_DATA_CHECKINS:
        return "low_data"
    return "good"


def quality_filter(quality: str):
    """SQL condition matching place_quality(p) == quality."""
    missing = and_(orm.Place.hours_source != "crawl", orm.Place.confidence != "high")
    if quality == "missing_hours":
        return missing
    if quality == "low_data":
        return and_(~missing, orm.Place.n_checkins < LOW_DATA_CHECKINS)
    return and_(~missing, orm.Place.n_checkins >= LOW_DATA_CHECKINS)


def search_filter(q: str):
    """Name ("Museum · An Khanh" matches label or ward), category, or dataset id prefix."""
    like = f"%{q.strip()}%"
    parts = [p.strip() for p in q.split("·") if p.strip()]
    conds = [orm.Place.label.ilike(like), orm.Place.ward.ilike(like), orm.Place.category.ilike(like),
             orm.Place.venue.ilike(f"{q.strip()}%")]
    if len(parts) == 2:
        conds.append(and_(orm.Place.label.ilike(f"%{parts[0]}%"), orm.Place.ward.ilike(f"%{parts[1]}%")))
    if q.strip().isdigit():
        conds.append(orm.Place.id == int(q.strip()))
    return or_(*conds)

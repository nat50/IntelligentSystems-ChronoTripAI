"""Saved trips, sharing, .gpx export and anonymous edit logs (Figma T4).

There are no accounts. Creating a trip returns an edit token once; the browser
keeps {id, token} pairs and sends the token as the X-Trip-Token header (or as
?token= on a download link). A trip shared with a link is readable by anyone
who has the slug, never editable.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import orm
from ..db import get_session
from ..schemas import (
    DayOverview, EditsIn, EditsOut, ItineraryOut, OptimizeRequest, ShareIn, SharedTripOut, TripCreated, TripIn,
    TripLookup, TripOut, TripPatch,
)
from ..services.versions import active_version

router = APIRouter(prefix="/api", tags=["trips"])
SessionDep = Annotated[Session, Depends(get_session)]
CITY_CODES = {"Ho Chi Minh City": "hcm", "Hanoi": "hn", "Da Nang": "dn"}
UTC_OFFSET = "+07:00"  # every served city is on Indochina Time


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _owned(s: Session, trip_id: int, token: str | None) -> orm.Trip:
    trip = s.get(orm.Trip, trip_id)
    # same answer for a missing trip and a wrong token, so ids cannot be probed
    if trip is None or not token or not hmac.compare_digest(trip.token_hash, _hash(token)):
        raise HTTPException(404, "Trip not found")
    return trip


def owned_trip(
    s: SessionDep, trip_id: int,
    x_trip_token: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query(description="edit token, for download links")] = None,
) -> orm.Trip:
    return _owned(s, trip_id, x_trip_token or token)


TripDep = Annotated[orm.Trip, Depends(owned_trip)]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _venues(s: Session, req: OptimizeRequest) -> dict[str, str]:
    rows = s.execute(select(orm.Place.id, orm.Place.venue).where(orm.Place.id.in_(req.place_ids))).all()
    return {str(pid): venue for pid, venue in rows}


def _remap(s: Session, trip: orm.Trip) -> tuple[OptimizeRequest, list[int]]:
    """The saved request with place ids of the active model version (ids change with every version).

    Places whose venue the active version no longer has are reported as stale and
    kept with their old id, so the frontend can tell the traveler to pick them again.
    """
    req = OptimizeRequest.model_validate(trip.request)
    v = active_version(s)
    venues = trip.venues or {}
    wanted = [venues.get(str(pid)) for pid in req.place_ids]
    current = dict(s.execute(
        select(orm.Place.venue, orm.Place.id).where(orm.Place.version == v, orm.Place.venue.in_([w for w in wanted if w]))
    ).all()) if v else {}
    new_id = {pid: current.get(venues.get(str(pid), ""), pid) for pid in req.place_ids}
    stale = [pid for pid in req.place_ids if venues.get(str(pid)) not in current]
    if all(new_id[pid] == pid for pid in req.place_ids):
        return req, stale
    data = req.model_dump(mode="json")
    data["place_ids"] = [new_id[p] for p in req.place_ids]
    data["must_visit"] = [new_id[p] for p in req.must_visit]
    data["locks"] = [{**lk, "place_id": new_id[lk["place_id"]]} for lk in data["locks"]]
    if data.get("seed_plan"):
        data["seed_plan"] = [[new_id[p] for p in day] for day in data["seed_plan"]]
    return OptimizeRequest.model_validate(data), stale


def _overview(trip: orm.Trip) -> list[DayOverview]:
    if not trip.itinerary:
        return []
    it = ItineraryOut.model_validate(trip.itinerary)
    return [
        DayOverview(
            day=d.day,
            date=trip.start_date + timedelta(days=d.day) if trip.start_date else None,
            stops=len(d.stops),
            travel_minutes=d.travel_minutes,
            first_stop=d.stops[0].start if d.stops else None,
            back_at=d.return_time,
        )
        for d in it.days
    ]


def _end_date(trip: orm.Trip) -> date | None:
    return trip.start_date + timedelta(days=trip.days - 1) if trip.start_date else None


def _status(trip: orm.Trip) -> str:
    if not trip.itinerary or trip.start_date is None:
        return "draft"
    return "past" if _end_date(trip) < date.today() else "upcoming"


def _out(s: Session, trip: orm.Trip) -> TripOut:
    req, stale = _remap(s, trip)
    return TripOut(
        id=trip.id, title=trip.title, city=trip.city, start_date=trip.start_date, end_date=_end_date(trip),
        days=trip.days, status=_status(trip),
        stops=sum(len(d["stops"]) for d in trip.itinerary["days"]) if trip.itinerary else 0,
        request=req, itinerary=trip.itinerary, overview=_overview(trip),
        share_enabled=trip.share_enabled, share_slug=trip.share_slug if trip.share_enabled else None,
        improve_estimates=trip.improve_estimates, stale_places=stale,
        created_at=trip.created_at, updated_at=trip.updated_at,
    )


def _apply_request(s: Session, trip: orm.Trip, req: OptimizeRequest) -> None:
    trip.request = req.model_dump(mode="json")
    trip.venues = {**(trip.venues or {}), **_venues(s, req)}
    trip.city, trip.days, trip.start_date = req.city, req.days, req.start_date


def _default_title(req: OptimizeRequest) -> str:
    return f"{req.city} · {req.days} day{'s' if req.days > 1 else ''}"


def _new_slug(s: Session, trip: orm.Trip) -> str:
    base = f"{CITY_CODES.get(trip.city, 'trip')}-{trip.days}d"
    while True:
        slug = f"{base}-{secrets.token_hex(3)}"
        if s.scalar(select(orm.Trip.id).where(orm.Trip.share_slug == slug)) is None:
            return slug


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post("/trips", response_model=TripCreated, status_code=201)
def create_trip(body: TripIn, s: SessionDep):
    token = secrets.token_urlsafe(24)
    trip = orm.Trip(
        token_hash=_hash(token), title=body.title or _default_title(body.request),
        itinerary=body.itinerary.model_dump(mode="json") if body.itinerary else None,
        improve_estimates=body.improve_estimates, share_enabled=False,
    )
    _apply_request(s, trip, body.request)
    s.add(trip)
    s.commit()
    s.refresh(trip)
    return TripCreated(**_out(s, trip).model_dump(), edit_token=token)


@router.post("/trips/lookup", response_model=list[TripOut])
def lookup_trips(body: TripLookup, s: SessionDep):
    """The saved trips of this browser, sorted by start date (trips without a date last).
    Unknown ids and wrong tokens are skipped, so a stale browser list does not fail."""
    trips = []
    for ref in body.trips:
        trip = s.get(orm.Trip, ref.id)
        if trip is not None and hmac.compare_digest(trip.token_hash, _hash(ref.token)):
            trips.append(trip)
    trips.sort(key=lambda t: (t.start_date is None, t.start_date or date.max, t.id))
    return [_out(s, t) for t in trips]


@router.get("/trips/{trip_id}", response_model=TripOut)
def get_trip(trip: TripDep, s: SessionDep):
    return _out(s, trip)


@router.patch("/trips/{trip_id}", response_model=TripOut)
def update_trip(body: TripPatch, trip: TripDep, s: SessionDep):
    if body.title is not None:
        trip.title = body.title
    if body.request is not None:
        _apply_request(s, trip, body.request)
    if "itinerary" in body.model_fields_set:
        trip.itinerary = body.itinerary.model_dump(mode="json") if body.itinerary else None
    if body.improve_estimates is not None:
        trip.improve_estimates = body.improve_estimates
    trip.updated_at = datetime.now(timezone.utc)
    s.commit()
    return _out(s, trip)


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip: TripDep, s: SessionDep):
    s.delete(trip)
    s.commit()
    return Response(status_code=204)


@router.put("/trips/{trip_id}/share", response_model=TripOut)
def share_trip(body: ShareIn, trip: TripDep, s: SessionDep):
    """Turn the share link on or off. The slug is kept, so turning it back on restores the same link."""
    if body.enabled and not trip.share_slug:
        trip.share_slug = _new_slug(s, trip)
    trip.share_enabled = body.enabled
    s.commit()
    return _out(s, trip)


@router.post("/trips/{trip_id}/edits", response_model=EditsOut)
def log_edits(body: EditsIn, trip: TripDep, s: SessionDep):
    """Anonymous edit logs for the data team (T4 "Help improve estimates" -> D1). Nothing is stored
    unless the traveler agreed, and what is stored has no trip or traveler id."""
    if not trip.improve_estimates:
        return EditsOut(stored=0)
    places = {}
    if trip.itinerary:
        it = ItineraryOut.model_validate(trip.itinerary)
        places = {st.place.id: st.place for d in it.days for st in d.stops} | {p.id: p for p in it.unscheduled}
    venues, version = trip.venues or {}, active_version(s) or ""
    for e in body.events:
        p = places.get(e.place_id) if e.place_id is not None else None
        s.add(orm.EditLog(
            city=trip.city, venue=venues.get(str(e.place_id), "") if e.place_id is not None else "",
            label=p.label if p else "", kind=e.kind, value=e.value,
            predicted_duration=p.duration if p else None, model_version=version,
        ))
    s.commit()
    return EditsOut(stored=len(body.events))


@router.get("/trips/{trip_id}/export.gpx")
def export_gpx(trip: TripDep):
    return _gpx_response(trip)


@router.get("/trips/{trip_id}/export.ics")
def export_ics(trip: TripDep):
    return _ics_response(trip)


@router.get("/shared/{slug}", response_model=SharedTripOut)
def shared_trip(slug: str, s: SessionDep):
    trip = _shared(s, slug)
    return SharedTripOut(
        title=trip.title, city=trip.city, start_date=trip.start_date, end_date=_end_date(trip), days=trip.days,
        itinerary=trip.itinerary, overview=_overview(trip),
    )


@router.get("/shared/{slug}/export.gpx")
def shared_gpx(slug: str, s: SessionDep):
    return _gpx_response(_shared(s, slug))


@router.get("/shared/{slug}/export.ics")
def shared_ics(slug: str, s: SessionDep):
    return _ics_response(_shared(s, slug))


def _shared(s: Session, slug: str) -> orm.Trip:
    trip = s.scalar(select(orm.Trip).where(orm.Trip.share_slug == slug, orm.Trip.share_enabled))
    if trip is None:
        raise HTTPException(404, "This link is not shared")
    return trip


# --------------------------------------------------------------------------- #
# .gpx (Figma T4 "Route file (.gpx) · Opens in map apps")
# --------------------------------------------------------------------------- #
def _gpx_response(trip: orm.Trip) -> Response:
    if not trip.itinerary:
        raise HTTPException(409, "Build the itinerary before exporting it")
    name = f"chronotrip-{CITY_CODES.get(trip.city, 'trip')}-{trip.days}d.gpx"
    return Response(
        to_gpx(trip), media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _time(trip: orm.Trip, day: int, minutes: int) -> str | None:
    if trip.start_date is None:
        return None
    d = trip.start_date + timedelta(days=day + minutes // (24 * 60))
    m = minutes % (24 * 60)
    return f"{d.isoformat()}T{m // 60:02d}:{m % 60:02d}:00{UTC_OFFSET}"


def to_gpx(trip: orm.Trip) -> str:
    """One waypoint per stop (with its planned start time when the trip has a date)
    and one route per day, from the stay through the stops and back."""
    it = ItineraryOut.model_validate(trip.itinerary)
    req = OptimizeRequest.model_validate(trip.request)
    stay = req.stay
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="ChronoTrip AI" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <metadata><name>{escape(trip.title)}</name></metadata>",
    ]
    for d in it.days:
        for k, st in enumerate(d.stops, 1):
            p = st.place
            t = _time(trip, d.day, st.start)
            clock = f"{st.start // 60 % 24:02d}:{st.start % 60:02d}"
            out.append(f'  <wpt lat="{p.lat:.6f}" lon="{p.lon:.6f}">')
            if t:
                out.append(f"    <time>{t}</time>")
            out.append(f"    <name>{escape(f'Day {d.day + 1} · {k}. {p.label} · {p.ward}')}</name>")
            out.append(f"    <desc>{escape(f'{clock} · about {p.duration} min · estimated')}</desc>")
            out.append("  </wpt>")
    for d in it.days:
        if not d.stops:
            continue
        out.append(f"  <rte><name>Day {d.day + 1}</name>")
        start = req.first_day_start if d.day == 0 and req.first_day_start else stay
        points = [(start.lat, start.lon, start.label)] + [(st.place.lat, st.place.lon, f"{st.place.label} · {st.place.ward}") for st in d.stops]
        points.append((stay.lat, stay.lon, stay.label))
        for lat, lon, label in points:
            out.append(f'    <rtept lat="{lat:.6f}" lon="{lon:.6f}"><name>{escape(label)}</name></rtept>')
        out.append("  </rte>")
    out.append("</gpx>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# .ics (Figma T4 "Calendar file (.ics) · Adds each stop as an event"), RFC 5545
# --------------------------------------------------------------------------- #
ICS_TZ = "Asia/Ho_Chi_Minh"  # UTC+7 all year, no daylight saving
ICS_TZ_BLOCK = [
    "BEGIN:VTIMEZONE", f"TZID:{ICS_TZ}",
    "BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:+0700", "TZOFFSETTO:+0700", "TZNAME:ICT",
    "END:STANDARD", "END:VTIMEZONE",
]


def _ics_response(trip: orm.Trip) -> Response:
    if not trip.itinerary:
        raise HTTPException(409, "Build the itinerary before exporting it")
    if trip.start_date is None:
        raise HTTPException(409, "Set a start date before exporting a calendar")
    name = f"chronotrip-{CITY_CODES.get(trip.city, 'trip')}-{trip.days}d.ics"
    return Response(
        to_ics(trip), media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Lines longer than 75 octets continue on the next line after a space (RFC 5545 3.1)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(cur)
            cur = ""
        cur += ch
    out.append(cur)
    return [out[0]] + [" " + part for part in out[1:]]


def _ics_local(trip: orm.Trip, day: int, minutes: int) -> str:
    d = trip.start_date + timedelta(days=day + minutes // (24 * 60))
    m = minutes % (24 * 60)
    return f"{d:%Y%m%d}T{m // 60:02d}{m % 60:02d}00"


def to_ics(trip: orm.Trip) -> str:
    """One event per stop, from the planned start to the planned departure, in local time."""
    it = ItineraryOut.model_validate(trip.itinerary)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ChronoTrip AI//Itinerary//EN", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_text(trip.title)}", f"X-WR-TIMEZONE:{ICS_TZ}", *ICS_TZ_BLOCK,
    ]
    for d in it.days:
        for k, st in enumerate(d.stops, 1):
            p = st.place
            note = f"Day {d.day + 1}, stop {k}. About {p.duration} min (estimated from check-ins)."
            if st.locked_start is not None:
                note += " Booked time."
            lines += [
                "BEGIN:VEVENT",
                f"UID:trip{trip.id}-d{d.day}-s{k}-{p.venue or p.id}@chronotrip",
                f"DTSTAMP:{stamp}",
                f"DTSTART;TZID={ICS_TZ}:{_ics_local(trip, d.day, st.start)}",
                f"DTEND;TZID={ICS_TZ}:{_ics_local(trip, d.day, st.depart)}",
                f"SUMMARY:{_ics_text(f'{p.label} · {p.ward}')}",
                f"LOCATION:{_ics_text(f'{p.label} · {p.ward}, {trip.city}')}",
                f"GEO:{p.lat:.6f};{p.lon:.6f}",
                f"DESCRIPTION:{_ics_text(note)}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"

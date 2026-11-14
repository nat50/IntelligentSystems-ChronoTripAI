from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Confidence = Literal["high", "medium", "low"]
HoursSource = Literal["crawl", "estimated"]


def parse_clock(v: str | int) -> int:
    """'08:30' or minutes -> minutes since midnight."""
    if isinstance(v, int):
        return v
    try:
        hh, mm = v.split(":")
        hour, minute = int(hh), int(mm)
    except (AttributeError, ValueError) as exc:
        raise ValueError("Clock values must use HH:MM") from exc
    if not 0 <= minute < 60 or not 0 <= hour <= 24 or hour == 24 and minute != 0:
        raise ValueError("Clock values must be between 00:00 and 24:00")
    return hour * 60 + minute


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    city: str
    ward: str
    lat: float
    lon: float
    category: str
    label: str
    group: str
    effort: int
    score: int
    duration: int
    open_min: int
    close_min: int
    golden_start: int
    golden_end: int
    confidence: Confidence
    n_checkins: int
    estimated: bool = True  # every attribute is a model estimate (spec II.5)
    # Added for the Figma screens T2 / D2. All have defaults, so older clients keep
    # working. Field by field: docs/frontend-integration.md
    duration_lo: int = 0  # typical visit length range (q25..q75 of M3), minutes
    duration_hi: int = 0
    hours_source: HoursSource = "estimated"  # "crawl": open_min / close_min are real opening hours
    closed_days: list[int] = Field(default_factory=list)  # weekdays the place is closed, 0 = Monday
    conf_m1: Confidence = "low"  # popularity (score)
    conf_m2: Confidence = "low"  # best time (golden_start / golden_end)
    conf_m3: Confidence = "low"  # visit length (duration)

    @model_validator(mode="after")
    def _range(self):
        # rows loaded before the range existed carry 0
        self.duration_lo = self.duration_lo or self.duration
        self.duration_hi = self.duration_hi or self.duration
        return self


class PlaceDetail(PlaceOut):
    hour_profile: list[float]
    n_users: int = 0
    n_visits: int = 0  # visits with a measured length (input of M3)
    one_time_share: float = 0.0  # share of users who checked in exactly once
    visit_hist: list[int] = Field(default_factory=list)  # visits per 20-min bin, last bin = 240+


class CityOut(BaseModel):
    name: str
    lat: float
    lon: float
    stay: dict
    places: int


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = "Stay"


class Preferences(BaseModel):
    pace: float = Field(0.5, ge=0, le=1)
    travel: float = Field(0.5, ge=0, le=1)
    strictness: float = Field(0.5, ge=0, le=1)


class Lock(BaseModel):
    place_id: int
    day: int = Field(ge=0, le=2)
    start: int | None = Field(None, ge=0, le=36 * 60, description="booked start, minutes since midnight")


class OptimizeRequest(BaseModel):
    city: str
    place_ids: list[int] = Field(min_length=1, max_length=30)
    days: int = Field(1, ge=1, le=3)
    start_date: date | None = None  # first trip day (T1); needed to honour closed weekdays
    day_start: int = Field(8 * 60, ge=0, le=24 * 60)
    day_end: int = Field(21 * 60 + 30, ge=0, le=24 * 60)
    stay: Point
    first_day_start: Point | None = None  # airport / station on day 1
    preferences: Preferences = Field(default_factory=Preferences)
    locks: list[Lock] = Field(default_factory=list)
    seed_plan: list[list[int]] | None = None  # current plan (place ids per day) to start from

    @field_validator("day_start", "day_end", mode="before")
    @classmethod
    def _clock(cls, v):
        return parse_clock(v)

    @model_validator(mode="after")
    def _check(self):
        place_ids = set(self.place_ids)
        if len(place_ids) != len(self.place_ids):
            raise ValueError("place_ids must be unique")
        if self.day_end - self.day_start < 120:
            raise ValueError("Each day needs at least two hours")
        if any(lock.day >= self.days for lock in self.locks):
            raise ValueError("A lock refers to a day outside the trip")
        lock_ids = [lock.place_id for lock in self.locks]
        if len(set(lock_ids)) != len(lock_ids):
            raise ValueError("A place can only have one lock")
        unknown_locks = sorted(set(lock_ids) - place_ids)
        if unknown_locks:
            raise ValueError(f"Locks must refer to selected places: {unknown_locks}")
        if self.seed_plan is not None:
            if len(self.seed_plan) > self.days:
                raise ValueError("seed_plan cannot contain more days than the trip")
            seed_ids = [place_id for day in self.seed_plan for place_id in day]
            if len(set(seed_ids)) != len(seed_ids):
                raise ValueError("seed_plan place_ids must be unique")
            unknown_seeds = sorted(set(seed_ids) - place_ids)
            if unknown_seeds:
                raise ValueError(f"seed_plan must refer to selected places: {unknown_seeds}")
        return self


class StopOut(BaseModel):
    place: PlaceOut
    arrive: int
    start: int
    depart: int
    wait: int
    travel_in: int
    golden: bool
    meal_break_before: int
    locked: bool
    locked_start: int | None
    late_by: int


class DayOut(BaseModel):
    day: int
    start: int
    return_time: int
    return_travel: int
    meal_break_before_return: int
    travel_minutes: int
    wait_minutes: int
    stops: list[StopOut]
    warnings: list[str]


class ItineraryOut(BaseModel):
    days: list[DayOut]
    unscheduled: list[PlaceOut]
    fitness: float
    generations: int
    runtime_s: float
    travel_source: Literal["osrm", "estimate"]
    weights: dict[str, float]
    warnings: list[str] = Field(default_factory=list)  # trip-level notes, e.g. a place closed on every trip day


class CountryStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    country: str
    checkins: int
    users: int
    venues: int
    source: str


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: str
    source: str
    created_at: datetime
    metrics: dict
    places: int
    is_active: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    status: str
    models: dict
    message: str
    version: str | None
    created_at: datetime
    finished_at: datetime | None


class AdminOverview(BaseModel):
    country_stats: list[CountryStatOut]
    versions: list[VersionOut]
    job: JobOut | None
    dataset_found: bool
    raw_dir: str


class DownloadProgress(BaseModel):
    stage: str | None = None
    file: str | None = None
    done: int | None = None
    total: int | None = None
    speed: float | None = None
    eta: float | None = None


class DatasetStatus(BaseModel):
    found: bool
    raw_dir: str
    running: bool
    progress: DownloadProgress | None
    error: str | None


class TrainRequest(BaseModel):
    source: Literal["auto", "dataset", "sample"] = "auto"

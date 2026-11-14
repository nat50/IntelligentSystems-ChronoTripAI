from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ml.categories import interest_of

Confidence = Literal["high", "medium", "low"]
HoursSource = Literal["crawl", "estimated"]
Interest = Literal["food", "culture", "nature", "nightlife", "shopping"]
PlaceQuality = Literal["good", "low_data", "missing_hours"]


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
    venue: str = ""  # dataset id of the place; stable across model versions (D2 "ID")
    interest: Interest = "culture"  # Figma interest chip, derived from the label

    @model_validator(mode="after")
    def _derived(self):
        # rows loaded before the range existed carry 0
        self.duration_lo = self.duration_lo or self.duration
        self.duration_hi = self.duration_hi or self.duration
        self.interest = interest_of(self.label, self.group)
        return self


class PlaceDetail(PlaceOut):
    hour_profile: list[float]
    n_users: int = 0
    n_visits: int = 0  # visits with a measured length (input of M3)
    one_time_share: float = 0.0  # share of users who checked in exactly once
    visit_hist: list[int] = Field(default_factory=list)  # visits per 20-min bin, last bin = 240+
    model_versions: dict[str, str] = Field(default_factory=dict)  # {"m1": "v3", ...}: version behind each output
    quality: PlaceQuality = "good"


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
    must_visit: list[int] = Field(default_factory=list)  # T2 "Mark as must-visit": scheduled first

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
        unknown_must = sorted(set(self.must_visit) - place_ids)
        if unknown_must:
            raise ValueError(f"must_visit must refer to selected places: {unknown_must}")
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
    plan_fit: PlanFit | None = None  # set when a must-visit place could not be scheduled (T3 "No plan fits")


class PlanFix(BaseModel):
    kind: Literal["add_day", "extend_day", "move_place", "drop_places"]
    label: str  # ready-to-show text, e.g. "Move Theme park to Day 2"
    patch: dict  # fields to replace in the OptimizeRequest before re-optimizing
    fits: bool  # a quick re-optimization scheduled every must-visit place with this fix
    recommended: bool = False


class PlanFit(BaseModel):
    missing: list[int]  # must-visit place ids left unscheduled
    day: int | None  # the day that is too full, when the missing places are locked to one
    needed_min: int  # visit time of the must-visit places (on that day, or over the trip)
    available_min: int  # time left for visits after travel (on that day, or over the trip)
    fixes: list[PlanFix]


class JobStep(BaseModel):
    key: str
    label: str
    done: bool


class OptimizeJobOut(BaseModel):
    id: str
    status: Literal["running", "done", "failed", "cancelled"]
    generation: int
    max_generations: int
    best_stops: int  # places scheduled in the best plan so far
    best_travel_min: int  # its travel time
    steps: list[JobStep]
    result: ItineraryOut | None = None
    error: str | None = None


# --------------------------------------------------------------------------- #
# Saved trips (Figma T4). No accounts: the edit token is the key to a trip.
# --------------------------------------------------------------------------- #
TripStatus = Literal["draft", "upcoming", "past"]


class TripIn(BaseModel):
    title: str | None = Field(None, max_length=120)
    request: OptimizeRequest
    itinerary: ItineraryOut | None = None
    improve_estimates: bool = False  # T4 "Help improve estimates" (anonymous edit logs)


class TripPatch(BaseModel):
    title: str | None = Field(None, max_length=120)
    request: OptimizeRequest | None = None
    itinerary: ItineraryOut | None = None
    improve_estimates: bool | None = None


class DayOverview(BaseModel):
    day: int
    date: date | None
    stops: int
    travel_minutes: int
    first_stop: int | None  # minutes since midnight
    back_at: int


class TripOut(BaseModel):
    id: int
    title: str
    city: str
    start_date: date | None
    end_date: date | None
    days: int
    status: TripStatus
    stops: int
    request: OptimizeRequest
    itinerary: ItineraryOut | None
    overview: list[DayOverview]
    share_enabled: bool
    share_slug: str | None
    improve_estimates: bool
    stale_places: list[int]  # place ids of the saved request that the active model version no longer has
    created_at: datetime
    updated_at: datetime


class TripCreated(TripOut):
    edit_token: str  # returned once; send it as X-Trip-Token to read, change, share or delete the trip


class SharedTripOut(BaseModel):
    title: str
    city: str
    start_date: date | None
    end_date: date | None
    days: int
    itinerary: ItineraryOut | None
    overview: list[DayOverview]


class TripRef(BaseModel):
    id: int
    token: str


class TripLookup(BaseModel):
    trips: list[TripRef] = Field(max_length=200)


class ShareIn(BaseModel):
    enabled: bool


class EditEvent(BaseModel):
    kind: Literal["move", "remove", "add", "lock", "unlock", "set_duration", "reoptimize"]
    place_id: int | None = None
    day: int | None = Field(None, ge=0, le=2)
    value: float | None = None  # new start (move / lock) or new visit length (set_duration), minutes


class EditsIn(BaseModel):
    events: list[EditEvent] = Field(min_length=1, max_length=500)


class EditsOut(BaseModel):
    stored: int  # 0 when the traveler has not agreed to share edits


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


# --------------------------------------------------------------------------- #
# Data console (Figma D1-D4)
# --------------------------------------------------------------------------- #
class SourceOut(BaseModel):
    key: str
    name: str
    provides: str
    rows: int | None
    updated: datetime | None
    status: Literal["imported", "synced", "missing", "outdated", "online", "estimate"]


class PipelineStep(BaseModel):
    key: str
    label: str
    value: str


class QualityIssue(BaseModel):
    key: str
    impact: Literal["high", "medium", "low"]
    title: str
    detail: str
    action: Literal["crawl_hours", "retrain", "review_places"] | None


class CityReady(BaseModel):
    name: str
    places: int
    ready: bool


class DataOverview(BaseModel):
    checkins: int
    checkins_period: str
    places: int
    cities: list[CityReady]
    last_run: datetime | None
    last_run_minutes: float | None
    dataset_version: str | None
    sources: list[SourceOut]
    pipeline: list[PipelineStep]
    issues: list[QualityIssue]


class CrawlStatus(BaseModel):
    running: bool
    places: int | None
    usable: int | None
    updated: datetime | None
    error: str | None


class ExplorerPlace(BaseModel):
    id: int
    venue: str
    name: str  # "<label> · <ward>"
    group: str
    n_checkins: int
    quality: PlaceQuality


class ExplorerPage(BaseModel):
    city: str
    total: int  # places of the city in the active version
    places: list[ExplorerPlace]


ModelKey = Literal["m1", "m2", "m3"]


class ModelVersionRow(BaseModel):
    version: str
    created_at: datetime
    source: str
    trained: bool  # this version trained the model (False: the model was copied from `origin`)
    origin: str  # version the model was trained in
    active: bool
    headline: dict  # main metric for the list, e.g. {"name": "MAE", "value": 11.8, "unit": "min"}
    metrics: dict
    settings: dict


class ModelCard(BaseModel):
    key: ModelKey
    name: str
    description: str
    active_version: str | None
    status: Literal["active", "training", "new_run_ready", "failed", "untrained"]
    progress: float | None  # 0..1 while training
    latest: str | None  # newest version that trained this model
    settings: dict  # current defaults for "Edit settings"
    split: dict  # time-based train / val / test split and its share of check-ins


class ModelDetail(ModelCard):
    versions: list[ModelVersionRow]


class ModelTrainIn(BaseModel):
    settings: dict = Field(default_factory=dict)


class ImpactOut(BaseModel):
    model: ModelKey
    version: str
    against: str  # the active version
    places_compared: int
    places_changed: int
    mean_change: float  # minutes (m3), points (m1) or minutes of best-time start (m2)
    unit: str
    trips_affected: int  # saved trips with at least one changed place
    message: str


class ObjectiveIn(BaseModel):
    popularity: float = Field(0.6, ge=0, le=1)
    golden: float = Field(0.3, ge=0, le=1)
    travel: float = Field(0.1, ge=0, le=1)

    @model_validator(mode="after")
    def _sum(self):
        if abs(self.popularity + self.golden + self.travel - 1.0) > 0.011:
            raise ValueError("Objective weights must sum to 1.0")
        return self


class OptimizerSettings(BaseModel):
    population: int = Field(100, ge=10, le=400)
    generations: int = Field(400, ge=10, le=2000)
    crossover: float = Field(0.85, ge=0, le=1)
    mutation: float = Field(0.15, ge=0, le=1)
    time_limit_s: float = Field(6.0, ge=0.5, le=30)
    local_search: bool = True
    objective: ObjectiveIn = Field(default_factory=ObjectiveIn)


class BenchmarkCase(BaseModel):
    name: str
    city: str
    places: int
    days: int
    score_active: float
    score_new: float
    violations: int
    runtime_s: float


class BenchmarkOut(BaseModel):
    id: int
    status: Literal["running", "done", "failed"]
    settings: OptimizerSettings
    active: OptimizerSettings
    score_change: float | None  # relative, e.g. 0.031 = +3.1%
    violations: int | None
    median_runtime_s: float | None
    curve: dict | None  # {"generation": [...], "active": [...], "new": [...]} for the first case
    cases: list[BenchmarkCase]
    ready_to_apply: bool
    error: str | None
    created_at: datetime


class OptimizerOut(BaseModel):
    active: OptimizerSettings
    updated_at: datetime | None
    last_benchmark: BenchmarkOut | None

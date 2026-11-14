from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Place(Base):
    """A candidate place with the attributes predicted by one model version."""

    __tablename__ = "places"
    __table_args__ = (
        Index("ix_places_version_city_score", "version", "city", "score"),
        Index("ix_places_version_latlon", "version", "lat", "lon"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(32))
    venue: Mapped[str] = mapped_column(String(64))
    city: Mapped[str] = mapped_column(String(64))
    ward: Mapped[str] = mapped_column(String(64))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(64))
    group: Mapped[str] = mapped_column(String(32))
    effort: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)
    open_min: Mapped[int] = mapped_column(Integer)
    close_min: Mapped[int] = mapped_column(Integer)
    golden_start: Mapped[int] = mapped_column(Integer)
    golden_end: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(8))
    n_checkins: Mapped[int] = mapped_column(Integer)
    n_users: Mapped[int] = mapped_column(Integer)
    hour_profile: Mapped[list] = mapped_column(JSON)
    # Added with the Figma-aligned models (docs/model-changes.md). Every column has a
    # server default, so db.init_db can add them to a table created by an older build.
    duration_lo: Mapped[int] = mapped_column(Integer, server_default="0")  # q25 of the visit length
    duration_hi: Mapped[int] = mapped_column(Integer, server_default="0")  # q75
    hours_source: Mapped[str] = mapped_column(String(16), server_default="estimated")  # crawl | estimated
    closed_days: Mapped[list] = mapped_column(JSON, server_default="[]")  # weekdays, 0 = Monday
    conf_m1: Mapped[str] = mapped_column(String(8), server_default="low")
    conf_m2: Mapped[str] = mapped_column(String(8), server_default="low")
    conf_m3: Mapped[str] = mapped_column(String(8), server_default="low")
    n_visits: Mapped[int] = mapped_column(Integer, server_default="0")
    one_time_share: Mapped[float] = mapped_column(Float, server_default="0")
    visit_hist: Mapped[list] = mapped_column(JSON, server_default="[]")


class ModelVersion(Base):
    __tablename__ = "model_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    places: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-model versions (Figma D3): which version each model was trained in, which
    # models this version trained itself, and the settings they were trained with.
    components: Mapped[dict] = mapped_column(JSON, server_default="{}")  # {"m1": "v1", "m2": "v3", "m3": "v3"}
    trained: Mapped[list] = mapped_column(JSON, server_default="[]")  # ["m3"]
    settings: Mapped[dict] = mapped_column(JSON, server_default="{}")  # {"m3": {...}}


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed
    models: Mapped[dict] = mapped_column(JSON, default=dict)  # {"m1": "queued|training|trained|failed"}
    message: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), server_default="full")  # full | model | compose
    target: Mapped[str] = mapped_column(String(8), server_default="")  # model key for kind model / compose


class Trip(Base):
    """A saved trip (Figma T4). There are no accounts: whoever holds the edit token owns it."""

    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the edit token
    title: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    days: Mapped[int] = mapped_column(Integer)
    request: Mapped[dict] = mapped_column(JSON)  # OptimizeRequest
    venues: Mapped[dict] = mapped_column(JSON)  # {place_id: venue} of the request, to survive new model versions
    itinerary: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ItineraryOut snapshot
    share_slug: Mapped[str | None] = mapped_column(String(48), unique=True, nullable=True)
    share_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    improve_estimates: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class EditLog(Base):
    """An anonymous itinerary edit shared with consent (T4 -> D1). No trip or user id is kept."""

    __tablename__ = "edit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city: Mapped[str] = mapped_column(String(64))
    venue: Mapped[str] = mapped_column(String(64), default="")
    label: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # new start or new visit length (min)
    predicted_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # M3 estimate at that time
    model_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OptimizerConfig(Base):
    """Optimizer settings applied to the planner from the D4 screen; the newest row is active."""

    __tablename__ = "optimizer_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | failed
    settings: Mapped[dict] = mapped_column(JSON)
    active: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CountryStat(Base):
    __tablename__ = "country_stats"

    country: Mapped[str] = mapped_column(String(4), primary_key=True)
    checkins: Mapped[int] = mapped_column(Integer)
    users: Mapped[int] = mapped_column(Integer)
    venues: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))

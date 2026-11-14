from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
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


class CountryStat(Base):
    __tablename__ = "country_stats"

    country: Mapped[str] = mapped_column(String(4), primary_key=True)
    checkins: Mapped[int] = mapped_column(Integer)
    users: Mapped[int] = mapped_column(Integer)
    venues: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))

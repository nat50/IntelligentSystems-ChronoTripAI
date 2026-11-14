"""Read models for the data console (Figma D1 Data, D2 Place explorer, D3 Models)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ml import hours
from ml.geo import SUPPORTED_CITIES
from ml.models import SETTINGS

from .. import orm
from ..config import get_settings
from ..schemas import (
    CityReady, CrawlStatus, DataOverview, ExplorerPage, ExplorerPlace, ImpactOut, ModelCard, ModelDetail,
    ModelVersionRow, PipelineStep, QualityIssue, SourceOut,
)
from .quality import LOW_DATA_CHECKINS, place_quality, quality_filter, search_filter
from .training import dataset_found, running_job
from .versions import active_version, components, trained

log = logging.getLogger(__name__)
CRAWL_MAX_AGE_DAYS = 30
CITY_READY_PLACES = 50  # a city is offered to travelers (T1) from this many places

MODEL_INFO = {
    "m1": ("M1 · Popularity", "Score 0–100 per place"),
    "m2": ("M2 · Hour profile", "Best hours to visit"),
    "m3": ("M3 · Visit length", "Minutes per stop"),
}


def _mtime(path) -> datetime | None:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) if path.exists() else None


def _active(s: Session) -> orm.ModelVersion | None:
    v = active_version(s)
    return s.get(orm.ModelVersion, v) if v else None


# --------------------------------------------------------------------------- #
# D1 · Data
# --------------------------------------------------------------------------- #
def data_overview(s: Session) -> DataOverview:
    settings = get_settings()
    mv = _active(s)
    summary = (mv.metrics or {}).get("summary", {}) if mv else {}
    quality = summary.get("data_quality", {})
    stats = s.scalars(select(orm.CountryStat)).all()
    checkins = sum(c.checkins for c in stats)
    vn = next((c.checkins for c in stats if c.country == "VN"), 0)
    counts = dict(s.execute(
        select(orm.Place.city, func.count()).where(orm.Place.version == mv.version).group_by(orm.Place.city)
    ).all()) if mv else {}
    places = sum(counts.values())

    last = s.scalar(
        select(orm.TrainingJob).where(orm.TrainingJob.status == "done", orm.TrainingJob.kind == "full")
        .order_by(orm.TrainingJob.id.desc())
    )
    last_run = last.finished_at if last else (mv.created_at if mv else None)
    minutes = None
    if last and last.finished_at and last.created_at:
        minutes = round((_aware(last.finished_at) - _aware(last.created_at)).total_seconds() / 60, 1)

    crawl_file = settings.raw_dir / hours.HOURS_FILE
    crawl_rows = len(json.loads(crawl_file.read_text(encoding="utf-8"))) if crawl_file.exists() else None
    crawl_time = _mtime(crawl_file)
    crawl_old = crawl_time is not None and (datetime.now(timezone.utc) - crawl_time).days > CRAWL_MAX_AGE_DAYS
    edit_count = s.scalar(select(func.count()).select_from(orm.EditLog)) or 0
    edit_last = s.scalar(select(func.max(orm.EditLog.created_at)))
    sources = [
        SourceOut(
            key="checkins", name="LBSN2Vec++ check-ins", provides="User check-ins with time", rows=checkins or None,
            updated=None, status="imported" if dataset_found() or (mv and mv.source == "dataset") else "missing",
        ),
        SourceOut(
            key="opening_hours", name="Place details (OpenStreetMap crawl)", provides="Opening hours, closed days",
            rows=crawl_rows, updated=crawl_time,
            status="missing" if crawl_rows is None else ("outdated" if crawl_old else "synced"),
        ),
        SourceOut(
            key="travel", name="OSRM travel time", provides="Road travel-time matrix", rows=len(SUPPORTED_CITIES),
            updated=None, status="online" if settings.osrm_url else "estimate",
        ),
        SourceOut(
            key="edit_logs", name="Traveler edit logs (T4, with consent)", provides="Changed visit lengths and times",
            rows=edit_count, updated=edit_last, status="synced" if edit_count else "missing",
        ),
    ]

    visits = quality.get("visits", {})
    opening = quality.get("opening_hours", {})
    pipeline = [
        PipelineStep(key="import", label="Import", value=f"{checkins / 1e6:.2f} M check-ins"),
        PipelineStep(key="clean", label="Clean visit lengths",
                     value=f"−{visits.get('raw', 0) - visits.get('kept', 0):,} visits" if visits else "–"),
        PipelineStep(key="match", label="Match opening hours",
                     value=f"{opening.get('matched', 0):,} places matched" if opening else "–"),
        PipelineStep(key="features", label="Build profiles", value=f"{places:,} places"),
        PipelineStep(key="publish", label="Publish", value=mv.version if mv else "–"),
    ]

    issues: list[QualityIssue] = []
    if mv:
        missing = s.scalar(select(func.count()).select_from(orm.Place).where(
            orm.Place.version == mv.version, quality_filter("missing_hours"))) or 0
        if missing:
            issues.append(QualityIssue(
                key="missing_hours", impact="high" if missing > 0.1 * max(places, 1) else "medium",
                title=f"{missing:,} places have no reliable opening hours",
                detail="No crawled hours and the estimate from check-ins is unstable; the planner treats their hours as soft.",
                action="crawl_hours",
            ))
        low = s.scalar(select(func.count()).select_from(orm.Place).where(
            orm.Place.version == mv.version, orm.Place.n_checkins < LOW_DATA_CHECKINS)) or 0
        if low:
            issues.append(QualityIssue(
                key="low_data", impact="low", title=f"{low:,} places have fewer than {LOW_DATA_CHECKINS} check-ins",
                detail="Their estimates lean on the ward, city and category priors.", action="review_places",
            ))
    if checkins and vn / checkins < 0.01:
        issues.append(QualityIssue(
            key="vietnam_share", impact="high",
            title=f"Vietnam has only {vn:,} check-ins ({100 * vn / checkins:.1f}%)",
            detail="Estimates for Vietnamese cities are less reliable; M1-M3 use regional (ward / city / category) priors.",
            action=None,
        ))
    if visits.get("over_max"):
        issues.append(QualityIssue(
            key="long_visits", impact="medium",
            title=f"{visits['over_max']:,} visits longer than {visits.get('max_dwell_min', 360) // 60} h",
            detail="Likely missing check-outs; they are left out of M3 training.", action=None,
        ))
    if crawl_old:
        issues.append(QualityIssue(
            key="crawl_outdated", impact="medium", title="Opening hours crawl is more than 30 days old",
            detail="Crawl again, then retrain to use the new hours.", action="crawl_hours",
        ))
    if edit_count:
        issues.append(QualityIssue(
            key="edit_logs", impact="low", title=f"{edit_count:,} anonymous traveler edits collected",
            detail="Not used by M3 yet; review them before the next training.", action=None,
        ))
    order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: order[i.impact])

    return DataOverview(
        checkins=checkins, checkins_period="Apr 2012 – Jan 2014", places=places,
        cities=[CityReady(name=c, places=counts.get(c, 0), ready=counts.get(c, 0) >= CITY_READY_PLACES)
                for c in SUPPORTED_CITIES],
        last_run=last_run, last_run_minutes=minutes, dataset_version=mv.version if mv else None,
        sources=sources, pipeline=pipeline, issues=issues,
    )


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# Opening-hours crawl started from D1 ("Re-crawl"); the next training uses it.
_crawl_lock = threading.Lock()
_crawl: dict = {"running": False, "error": None}


def crawl_status() -> CrawlStatus:
    path = get_settings().raw_dir / hours.HOURS_FILE
    places = usable = None
    if path.exists():
        places = len(json.loads(path.read_text(encoding="utf-8")))
        parsed = hours.load(get_settings().raw_dir)
        usable = 0 if parsed is None else len(parsed)
    with _crawl_lock:
        return CrawlStatus(running=_crawl["running"], places=places, usable=usable, updated=_mtime(path),
                           error=_crawl["error"])


def start_crawl() -> CrawlStatus:
    with _crawl_lock:
        if _crawl["running"]:
            raise RuntimeError("The opening-hours crawl is already running")
        _crawl.update(running=True, error=None)

    def run() -> None:
        try:
            hours.fetch(get_settings().raw_dir)
        except Exception as exc:  # shown on D1
            log.exception("opening-hours crawl failed")
            with _crawl_lock:
                _crawl["error"] = str(exc)[:500]
        finally:
            with _crawl_lock:
                _crawl["running"] = False

    threading.Thread(target=run, daemon=True, name="hours-crawl").start()
    return crawl_status()


# --------------------------------------------------------------------------- #
# D2 · Place explorer
# --------------------------------------------------------------------------- #
def explorer(s: Session, version: str, city: str, q: str | None, quality: str | None, limit: int, offset: int) -> ExplorerPage:
    base = select(orm.Place).where(orm.Place.version == version, orm.Place.city == city)
    total = s.scalar(select(func.count()).select_from(base.subquery())) or 0
    if q and q.strip():
        base = base.where(search_filter(q))
    if quality:
        base = base.where(quality_filter(quality))
    rows = s.scalars(base.order_by(orm.Place.n_checkins.desc(), orm.Place.id).offset(offset).limit(limit)).all()
    return ExplorerPage(
        city=city, total=total,
        places=[ExplorerPlace(id=p.id, venue=p.venue, name=f"{p.label} · {p.ward}", group=p.group,
                              n_checkins=p.n_checkins, quality=place_quality(p)) for p in rows],
    )


# --------------------------------------------------------------------------- #
# D3 · Models
# --------------------------------------------------------------------------- #
def _headline(model: str, metrics: dict) -> dict:
    if model == "m1":
        v = metrics.get("spearman_all", metrics.get("spearman"))
        return {"name": "Spearman", "value": v, "baseline": metrics.get("spearman_all_baseline"), "unit": "", "higher_is_better": True}
    if model == "m2":
        return {"name": "Log-likelihood", "value": metrics.get("loglik"), "baseline": metrics.get("loglik_baseline"),
                "unit": "", "higher_is_better": True}
    return {"name": "MAE", "value": metrics.get("mae", metrics.get("pinball")), "baseline": metrics.get("mae_baseline"),
            "unit": "min", "higher_is_better": False}


def _split(mv: orm.ModelVersion | None) -> dict:
    q = ((mv.metrics or {}).get("summary", {}) if mv else {}).get("data_quality", {})
    counts, dates = q.get("split_counts", {}), q.get("split_dates", {})
    total = sum(counts.values())
    return {
        "kind": "time",
        "train_end": dates.get("train_end"), "val_end": dates.get("val_end"),
        "shares": {k: round(v / total, 3) for k, v in counts.items()} if total else {},
    }


def _defaults(model: str, mv: orm.ModelVersion | None) -> dict:
    used = ((mv.settings or {}) if mv else {}).get(model)
    return used or {name: spec[0] for name, spec in SETTINGS[model].items()}


def model_card(s: Session, model: str, versions: list[orm.ModelVersion] | None = None) -> ModelCard:
    versions = versions if versions is not None else s.scalars(
        select(orm.ModelVersion).order_by(orm.ModelVersion.created_at.desc())).all()
    active = next((mv for mv in versions if mv.is_active), None)
    active_origin = components(active)[model] if active else None
    runs = [mv for mv in versions if model in trained(mv)]
    latest = runs[0].version if runs else None

    status, progress = ("active" if active else "untrained"), None
    job = running_job()
    if job and (job.kind == "full" or job.target == model) and model in (job.models or {}):
        status = "training"
        progress = {"queued": 0.0, "training": 0.5, "trained": 1.0}.get(job.models[model], 0.0)
    else:
        last = s.scalar(select(orm.TrainingJob).where(
            (orm.TrainingJob.target == model) | (orm.TrainingJob.kind == "full")).order_by(orm.TrainingJob.id.desc()))
        if last is not None and last.status == "failed" and model in (last.models or {}):
            status = "failed"
        elif latest and active_origin and latest != active_origin:
            # a run newer than the one in use waits to be activated (an older one means a rollback happened)
            origin = next((mv for mv in versions if mv.version == active_origin), None)
            if origin is None or _aware(runs[0].created_at) > _aware(origin.created_at):
                status = "new_run_ready"
    name, description = MODEL_INFO[model]
    return ModelCard(
        key=model, name=name, description=description, active_version=active_origin, status=status,
        progress=progress, latest=latest, settings=_defaults(model, active), split=_split(active),
    )


def model_detail(s: Session, model: str) -> ModelDetail:
    versions = s.scalars(select(orm.ModelVersion).order_by(orm.ModelVersion.created_at.desc())).all()
    card = model_card(s, model, versions)
    rows = [
        ModelVersionRow(
            version=mv.version, created_at=mv.created_at, source=mv.source, trained=True, origin=mv.version,
            active=card.active_version == mv.version,
            headline=_headline(model, (mv.metrics or {}).get(model, {})),
            metrics=(mv.metrics or {}).get(model, {}), settings=(mv.settings or {}).get(model, {}),
        )
        for mv in versions if model in trained(mv)
    ]
    return ModelDetail(**card.model_dump(), versions=rows)


IMPACT = {  # column compared, threshold for "changed", unit, sentence
    "m1": ("score", 5, "points", "Popularity scores shown in T2 change by {mean:+.1f} points per place on average."),
    "m2": ("golden_start", 60, "min", "Best times shown in T2 move by {mean:+.0f} min per place on average."),
    "m3": ("duration", 5, "min", "Visit-length estimates shown in T2 change by {mean:+.1f} min per stop on average."),
}


def impact(s: Session, model: str, version: str) -> ImpactOut:
    """What activating `model` from `version` would change, measured on the attribute table that
    `version` produced (the other two models of that version may differ slightly from the active ones)."""
    mv = _active(s)
    if mv is None:
        raise LookupError("No model version is active")
    if s.get(orm.ModelVersion, version) is None:
        raise KeyError(version)
    column, threshold, unit, sentence = IMPACT[model]
    col = getattr(orm.Place, column)
    new = dict(s.execute(select(orm.Place.venue, col).where(orm.Place.version == version)).all())
    old = dict(s.execute(select(orm.Place.venue, col).where(orm.Place.version == mv.version)).all())
    common = [v for v in new if v in old]
    diffs = {v: new[v] - old[v] for v in common}
    changed = {v for v, d in diffs.items() if abs(d) >= threshold}
    mean = sum(diffs.values()) / len(diffs) if diffs else 0.0
    trips = 0
    for venues in s.scalars(select(orm.Trip.venues)):
        if changed & set((venues or {}).values()):
            trips += 1
    message = sentence.format(mean=mean)
    message += f" {trips:,} saved trip{'s' if trips != 1 else ''} include{'s' if trips == 1 else ''} a changed place."
    return ImpactOut(
        model=model, version=version, against=mv.version, places_compared=len(common), places_changed=len(changed),
        mean_change=round(mean, 2), unit=unit, trips_affected=trips, message=message,
    )

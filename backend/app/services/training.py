"""Background training jobs started from the admin screen (FR-06, Figma D3).

Three kinds of job, one at a time:
  full     preprocess the raw files and train M1-M3 (activated if nothing is active yet)
  model    train one model; the other two are copied from the active version ("New run ready")
  compose  build a version from the active one with one model taken from another version,
           then activate it (D3 "Activate" / "Roll back")
"""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from ml import pipeline
from ml.models import check_settings
from ml.preprocess import CHECKIN_FILE, POI_FILE, find_raw
from ml.sample import write_sample

from .. import orm
from ..config import get_settings
from ..db import SessionLocal
from .versions import activate, active_version, components, register_version

log = logging.getLogger(__name__)
_lock = threading.Lock()


def dataset_found() -> bool:
    raw = get_settings().raw_dir
    return raw.exists() and find_raw(raw, POI_FILE) is not None and find_raw(raw, CHECKIN_FILE) is not None


def running_job() -> orm.TrainingJob | None:
    with SessionLocal() as s:
        return s.scalar(select(orm.TrainingJob).where(orm.TrainingJob.status.in_(["queued", "running"])))


def _create(source: str, models: tuple[str, ...], kind: str, target: str = "") -> orm.TrainingJob:
    with _lock:
        if running_job():
            raise RuntimeError("A training job is already running")
        with SessionLocal() as s:
            job = orm.TrainingJob(
                source=source, status="queued", models={m: "queued" for m in models}, message="Queued",
                kind=kind, target=target,
            )
            s.add(job)
            s.commit()
            s.refresh(job)
            return job


def start(source: str) -> orm.TrainingJob:
    if source == "auto":
        source = "dataset" if dataset_found() else "sample"
    if source == "dataset" and not dataset_found():
        raise FileNotFoundError(f"Put {POI_FILE} and {CHECKIN_FILE} in {get_settings().raw_dir}")
    job = _create(source, pipeline.MODELS, "full")
    threading.Thread(target=_run, args=(job.id, source), daemon=True, name=f"train-{job.id}").start()
    return job


def _active() -> orm.ModelVersion:
    with SessionLocal() as s:
        v = active_version(s)
        mv = s.get(orm.ModelVersion, v) if v else None
        if mv is None:
            raise LookupError("Train and activate a full version first")
        return mv


def _processed_for(mv: orm.ModelVersion):
    settings = get_settings()
    processed = pipeline.processed_dir(settings.data_dir, mv.source)
    if not (processed / "venues.parquet").exists():
        raise LookupError(f"Preprocessed data for '{mv.source}' is missing; run a full training first")
    return processed


def start_model(model: str, settings: dict) -> orm.TrainingJob:
    """Train one model on the data of the active version; the result is not activated."""
    settings = check_settings(model, settings)  # ValueError -> 422
    base = _active()
    processed = _processed_for(base)
    job = _create(base.source, (model,), "model", model)
    threading.Thread(
        target=_run_model, args=(job.id, model, settings, base.version, processed, base.source), daemon=True,
        name=f"train-{model}-{job.id}",
    ).start()
    return job


def start_compose(model: str, version: str) -> orm.TrainingJob:
    """Activate `model` from `version`: the active version with that one model swapped, as a new version."""
    base = _active()
    with SessionLocal() as s:
        src = s.get(orm.ModelVersion, version)
        if src is None:
            raise KeyError(version)
        target = {**components(base), model: components(src)[model]}  # by the version that trained each model
        if target == components(base):
            raise RuntimeError(f"{model.upper()} from {version} is already active")
        # a version that already holds exactly these models (e.g. a rollback): activate it, nothing to build
        existing = next(
            (mv.version for mv in s.scalars(select(orm.ModelVersion).order_by(orm.ModelVersion.created_at.desc()))
             if components(mv) == target and mv.source == base.source),
            None,
        )
    if existing is not None:
        job = _create(base.source, (model,), "compose", model)
        with SessionLocal() as s:
            activate(s, existing)
        _update(job.id, status="done", version=existing, models={model: "trained"},
                finished_at=datetime.now(timezone.utc), message=f"Activated {existing}")
        with SessionLocal() as s:
            return s.get(orm.TrainingJob, job.id)
    processed = _processed_for(base)
    picks = {m: (version if m == model else base.version) for m in pipeline.MODELS}
    job = _create(base.source, (model,), "compose", model)
    threading.Thread(target=_run_compose, args=(job.id, model, picks, processed), daemon=True,
                     name=f"compose-{job.id}").start()
    return job


def _update(job_id: int, **fields) -> None:
    with SessionLocal() as s:
        job = s.get(orm.TrainingJob, job_id)
        for k, v in fields.items():
            setattr(job, k, v)
        s.commit()


def _status_fn(job_id: int, models: dict):
    def status(model: str, state: str, info: dict | None) -> None:
        if model in models:
            models[model] = state
            _update(job_id, models=dict(models), message=f"{model.upper()} {state}")
        elif state == "preprocessing":
            _update(job_id, message=(info or {}).get("message", "Preprocessing"))
        elif state == "inferring":
            _update(job_id, message="Predicting attributes for every place")

    return status


def _fail(job_id: int, models: dict, exc: Exception) -> None:
    log.exception("training job %s failed", job_id)
    failed = {m: ("failed" if s in ("queued", "training") else s) for m, s in models.items()}
    _update(job_id, status="failed", models=failed, message=str(exc)[:500], finished_at=datetime.now(timezone.utc))


def _done(job_id: int, meta: dict, activate_now: bool) -> None:
    settings = get_settings()
    with SessionLocal() as s:
        register_version(s, settings.model_dir / meta["version"])
        if activate_now or active_version(s) is None:
            activate(s, meta["version"])
    _update(
        job_id, status="done", version=meta["version"], finished_at=datetime.now(timezone.utc),
        message=f"Saved {meta['version']} · {meta['places']} places",
    )


def _run(job_id: int, source: str) -> None:
    settings = get_settings()
    models = {m: "queued" for m in pipeline.MODELS}
    try:
        _update(job_id, status="running", message="Starting")
        raw = settings.raw_dir
        if source == "sample":
            raw = settings.data_dir / "sample_raw"
            shutil.rmtree(raw, ignore_errors=True)
            write_sample(raw)
        version = pipeline.next_version(settings.model_dir)
        meta = pipeline.run(
            raw, settings.data_dir, settings.model_dir,
            source="dataset" if source == "dataset" else "synthetic-sample", status=_status_fn(job_id, models),
            version=version,
        )
        _done(job_id, meta, activate_now=False)
    except Exception as exc:  # report any failure on the admin screen
        _fail(job_id, models, exc)


def _run_model(job_id: int, model: str, model_settings: dict, base: str, processed, source: str) -> None:
    settings = get_settings()
    models = {model: "queued"}
    try:
        _update(job_id, status="running", message="Starting")
        meta = pipeline.train_all(
            processed, settings.model_dir, source=source, status=_status_fn(job_id, models),
            models=(model,), base=settings.model_dir / base, settings={model: model_settings},
        )
        _done(job_id, meta, activate_now=False)
    except Exception as exc:
        _fail(job_id, models, exc)


def _run_compose(job_id: int, model: str, picks: dict, processed) -> None:
    settings = get_settings()
    models = {model: "queued"}
    try:
        _update(job_id, status="running", message="Building the version")
        meta = pipeline.compose(processed, settings.model_dir, picks, status=_status_fn(job_id, models))
        _done(job_id, meta, activate_now=True)
    except Exception as exc:
        _fail(job_id, models, exc)

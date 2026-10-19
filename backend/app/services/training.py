"""Background training jobs started from the admin screen (FR-06)."""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from ml import pipeline
from ml.preprocess import CHECKIN_FILE, POI_FILE, find_raw
from ml.sample import write_sample

from .. import orm
from ..config import get_settings
from ..db import SessionLocal
from .versions import activate, active_version, register_version

log = logging.getLogger(__name__)
_lock = threading.Lock()


def dataset_found() -> bool:
    raw = get_settings().raw_dir
    return raw.exists() and find_raw(raw, POI_FILE) is not None and find_raw(raw, CHECKIN_FILE) is not None


def running_job() -> orm.TrainingJob | None:
    with SessionLocal() as s:
        return s.scalar(select(orm.TrainingJob).where(orm.TrainingJob.status.in_(["queued", "running"])))


def start(source: str) -> orm.TrainingJob:
    if source == "auto":
        source = "dataset" if dataset_found() else "sample"
    if source == "dataset" and not dataset_found():
        raise FileNotFoundError(f"Put {POI_FILE} and {CHECKIN_FILE} in {get_settings().raw_dir}")
    with _lock:
        if running_job():
            raise RuntimeError("A training job is already running")
        with SessionLocal() as s:
            job = orm.TrainingJob(
                source=source, status="queued", models={m: "queued" for m in pipeline.MODELS}, message="Queued"
            )
            s.add(job)
            s.commit()
            s.refresh(job)
    threading.Thread(target=_run, args=(job.id, source), daemon=True, name=f"train-{job.id}").start()
    return job


def _update(job_id: int, **fields) -> None:
    with SessionLocal() as s:
        job = s.get(orm.TrainingJob, job_id)
        for k, v in fields.items():
            setattr(job, k, v)
        s.commit()


def _run(job_id: int, source: str) -> None:
    settings = get_settings()
    models = {m: "queued" for m in pipeline.MODELS}

    def status(model: str, state: str, info: dict | None) -> None:
        if model in models:
            models[model] = state
            _update(job_id, models=dict(models), message=f"{model.upper()} {state}")
        elif state == "preprocessing":
            _update(job_id, message=(info or {}).get("message", "Preprocessing"))
        elif state == "inferring":
            _update(job_id, message="Predicting attributes for every place")

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
            source="dataset" if source == "dataset" else "synthetic-sample", status=status, version=version,
        )
        with SessionLocal() as s:
            register_version(s, settings.model_dir / meta["version"])
            if active_version(s) is None:
                activate(s, meta["version"])
        _update(
            job_id, status="done", version=meta["version"], finished_at=datetime.now(timezone.utc),
            message=f"Saved {meta['version']} · {meta['places']} places",
        )
    except Exception as exc:  # report any failure on the admin screen
        log.exception("training job %s failed", job_id)
        failed = {m: ("failed" if s in ("queued", "training") else s) for m, s in models.items()}
        _update(job_id, status="failed", models=failed, message=str(exc)[:500], finished_at=datetime.now(timezone.utc))

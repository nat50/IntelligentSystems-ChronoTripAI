"""Optimizer settings and benchmarks (Figma D4), and optimize jobs with progress (Figma T3).

Settings: the newest OptimizerConfig row is what the planner uses ("Apply to planner").
Benchmark: fixed test cases built from the active model version, each solved with
the active and the candidate settings, `RUNS` times, median kept.
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ml.geo import DEFAULT_STAY

from .. import orm
from ..db import SessionLocal
from ..schemas import JobStep, OptimizeJobOut, OptimizerSettings, OptimizeRequest
from . import planner
from .versions import active_version

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Active settings
# --------------------------------------------------------------------------- #
def active_settings(s: Session) -> tuple[OptimizerSettings, datetime | None]:
    row = s.scalar(select(orm.OptimizerConfig).order_by(orm.OptimizerConfig.id.desc()))
    if row is None:
        return OptimizerSettings(), None
    return OptimizerSettings.model_validate(row.settings), row.created_at


def apply(s: Session, settings: OptimizerSettings) -> OptimizerSettings:
    s.add(orm.OptimizerConfig(settings=settings.model_dump()))
    s.commit()
    return settings


# --------------------------------------------------------------------------- #
# Optimize jobs (T3 "Building your itinerary...")
# --------------------------------------------------------------------------- #
STEPS = (("hours", "Opening hours checked"), ("travel", "Travel times loaded"), ("search", "Searching for the best order"))
MAX_JOBS = 100
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _job_out(job: dict) -> OptimizeJobOut:
    done_steps = job["done_steps"]
    return OptimizeJobOut(
        id=job["id"], status=job["status"], generation=job["generation"], max_generations=job["max_generations"],
        best_stops=job["stops"], best_travel_min=round(job["travel"]),
        steps=[JobStep(key=k, label=label, done=k in done_steps) for k, label in STEPS],
        result=job["result"], error=job["error"],
    )


def start_job(req: OptimizeRequest, places: list[orm.Place], settings: OptimizerSettings) -> OptimizeJobOut:
    job_id = uuid.uuid4().hex[:16]
    job = {
        "id": job_id, "status": "running", "generation": 0, "max_generations": settings.generations,
        "stops": 0, "travel": 0.0, "done_steps": set(), "result": None, "error": None, "cancel": False,
        "created": time.monotonic(),
    }
    with _jobs_lock:
        if len(_jobs) >= MAX_JOBS:  # forget the oldest finished jobs
            for old in sorted((j for j in _jobs.values() if j["status"] != "running"), key=lambda j: j["created"]):
                _jobs.pop(old["id"], None)
                if len(_jobs) < MAX_JOBS:
                    break
        _jobs[job_id] = job

    def progress(event: dict) -> bool:
        with _jobs_lock:
            step = event["step"]
            if step == "travel":
                job["done_steps"].add("hours")
            if step == "search":
                job["done_steps"].update({"hours", "travel"})
                job.update(generation=event["generation"], max_generations=event["max_generations"],
                           stops=event["stops"], travel=event["travel"])
            else:
                job["done_steps"].add(step)
            return not job["cancel"]

    def run() -> None:
        try:
            result = planner.optimize(req, places, settings, progress=progress)
            with _jobs_lock:
                job["done_steps"].update(k for k, _ in STEPS)
                job.update(status="done", result=result)
        except planner.Cancelled:
            with _jobs_lock:
                job["status"] = "cancelled"
        except Exception as exc:  # shown in the dialog
            log.exception("optimize job %s failed", job_id)
            with _jobs_lock:
                job.update(status="failed", error=str(exc)[:500])

    threading.Thread(target=run, daemon=True, name=f"optimize-{job_id}").start()
    return get_job(job_id)


def get_job(job_id: str) -> OptimizeJobOut | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return _job_out(job) if job else None


def cancel_job(job_id: str) -> OptimizeJobOut | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        job["cancel"] = True
        return _job_out(job)


# --------------------------------------------------------------------------- #
# Benchmark (D4)
# --------------------------------------------------------------------------- #
# name, city, places, days. Trips are capped at 30 places (spec), so the largest case is 30.
CASES = (
    ("HCM · 30 places · 3 days", "Ho Chi Minh City", 30, 3),
    ("HCM · 15 places · 1 day", "Ho Chi Minh City", 15, 1),
    ("Da Nang · 20 places · 2 days", "Da Nang", 20, 2),
    ("Hanoi · 25 places · 3 days", "Hanoi", 25, 3),
)
RUNS = 3
_bench_lock = threading.Lock()


def _case_places(s: Session, version: str, city: str, n: int) -> list[orm.Place]:
    """A fixed, varied pick: the top places of the city by score, at most 4 of one label."""
    rows = s.scalars(
        select(orm.Place).where(orm.Place.version == version, orm.Place.city == city)
        .order_by(orm.Place.score.desc(), orm.Place.id).limit(400)
    ).all()
    picked, per_label = [], {}
    for p in rows:
        if per_label.get(p.label, 0) < 4:
            picked.append(p)
            per_label[p.label] = per_label.get(p.label, 0) + 1
        if len(picked) == n:
            break
    return picked


def _violations(it) -> int:
    """Hard-rule breaks of a plan: a visit past closing time or a day that ends late."""
    late_stops = sum(1 for d in it.days for st in d.stops if st.late_by > 0)
    late_days = sum(1 for d in it.days if any(w.startswith("Back about") for w in d.warnings))
    return late_stops + late_days


def _case_request(places, city: str, days: int) -> OptimizeRequest:
    slat, slon, label = DEFAULT_STAY[city]
    return OptimizeRequest(
        city=city, place_ids=[p.id for p in places], days=days, day_start=8 * 60, day_end=21 * 60 + 30,
        stay={"lat": slat, "lon": slon, "label": label},
    )


def _run_case(places, city: str, days: int, settings: OptimizerSettings) -> tuple[float, int, float]:
    t0 = time.perf_counter()
    it = planner.optimize(_case_request(places, city, days), places, settings)
    return it.fitness, _violations(it), time.perf_counter() - t0


def start_benchmark(s: Session, settings: OptimizerSettings) -> orm.Benchmark:
    if not _bench_lock.acquire(blocking=False):
        raise RuntimeError("A benchmark is already running")
    try:
        active, _ = active_settings(s)
        version = active_version(s)
        if version is None:
            raise RuntimeError("No model version is active yet")
        row = orm.Benchmark(status="running", settings=settings.model_dump(), active=active.model_dump())
        s.add(row)
        s.commit()
        s.refresh(row)
    except Exception:
        _bench_lock.release()
        raise
    threading.Thread(target=_benchmark, args=(row.id, version, active, settings), daemon=True,
                     name=f"benchmark-{row.id}").start()
    return row


def _benchmark(bench_id: int, version: str, active: OptimizerSettings, new: OptimizerSettings) -> None:
    try:
        cases, curve = [], None
        with SessionLocal() as s:
            inputs = [(name, city, n, days, _case_places(s, version, city, n)) for name, city, n, days in CASES]
        for k, (name, city, n, days, places) in enumerate(inputs):
            if len(places) < min(n, 5):
                continue  # the city has no data in this version
            runs = {"active": [], "new": []}
            for which, st in (("active", active), ("new", new)):
                for _ in range(RUNS):
                    runs[which].append(_run_case(places, city, days, st))
            med = {w: statistics.median(r[0] for r in rs) for w, rs in runs.items()}
            cases.append({
                "name": name, "city": city, "places": len(places), "days": days,
                "score_active": round(med["active"], 2), "score_new": round(med["new"], 2),
                "violations": int(statistics.median(r[1] for r in runs["new"])),
                "runtime_s": round(statistics.median(r[2] for r in runs["new"]), 2),
            })
            if curve is None:
                curve = _fitness_curves(places, city, days, active, new)
        if not cases:
            raise RuntimeError("No benchmark case has places in the active model version")
        change = statistics.mean(
            (c["score_new"] - c["score_active"]) / abs(c["score_active"]) if c["score_active"] else 0.0 for c in cases
        )
        violations = sum(c["violations"] for c in cases)
        runtime = statistics.median(c["runtime_s"] for c in cases)
        result = {
            "cases": cases, "score_change": round(change, 4), "violations": violations,
            "median_runtime_s": round(runtime, 2), "curve": curve,
            "ready_to_apply": change >= 0 and violations == 0 and runtime <= new.time_limit_s + 1.0,
        }
        _finish(bench_id, "done", result, None)
    except Exception as exc:
        log.exception("benchmark %s failed", bench_id)
        _finish(bench_id, "failed", {}, str(exc)[:500])
    finally:
        _bench_lock.release()


def _fitness_curves(places, city, days, active: OptimizerSettings, new: OptimizerSettings) -> dict:
    """Best fitness per generation (the D4 chart), one run each on the first case."""
    from solver import solve

    out = {}
    req = _case_request(places, city, days)
    for which, st in (("active", active), ("new", new)):
        problem, _ = planner.build_problem(req, places, st)
        out[which] = [round(float(v), 2) for v in solve(problem, planner.ga_config(st)).history]
    longest = max(len(v) for v in out.values())
    step = max(1, longest // 60)
    return {
        "generation": list(range(0, longest, step)),
        **{w: [v[min(i, len(v) - 1)] for i in range(0, longest, step)] for w, v in out.items()},
    }


def _finish(bench_id: int, status: str, result: dict, error: str | None) -> None:
    with SessionLocal() as s:
        row = s.get(orm.Benchmark, bench_id)
        row.status, row.result, row.error = status, result, error
        s.commit()


def benchmark_out(row: orm.Benchmark):
    from ..schemas import BenchmarkOut

    r = row.result or {}
    return BenchmarkOut(
        id=row.id, status=row.status, settings=row.settings, active=row.active,
        score_change=r.get("score_change"), violations=r.get("violations"),
        median_runtime_s=r.get("median_runtime_s"), curve=r.get("curve"), cases=r.get("cases", []),
        ready_to_apply=bool(r.get("ready_to_apply")), error=row.error,
        created_at=row.created_at or datetime.now(timezone.utc),
    )

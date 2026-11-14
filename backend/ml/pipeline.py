"""Offline training + batch inference (spec IV.2 a-b).

    python -m ml.pipeline --raw data/raw            # full run on the real dataset
    python -m ml.pipeline --sample                  # synthetic sample in the same format

A run writes data/models/<version>/ with the three models, metrics and the
attribute table (attributes.parquet) for every candidate place in the
supported cities. Activating a version loads that table into the database.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import preprocess
from .geo import SUPPORTED_CITIES
from .models import (
    BEST_MINUTES, STABLE_HIGH, STABLE_MEDIUM, M1Popularity, M2HourProfile, M3VisitLength,
    best_starts, circular_smooth, fallback_duration, hour_windows, level,
)

log = logging.getLogger(__name__)

MODELS = ("m1", "m2", "m3")
StatusFn = Callable[[str, str, dict | None], None]  # (model or "pipeline", status, info)
VISIT_BIN_MIN = 20
VISIT_BIN_EDGES = list(range(0, 241, VISIT_BIN_MIN))  # lower edge of each bin, the last one is "240+"
ATTRIBUTE_COLUMNS = [
    "venue", "city", "ward", "lat", "lon", "category", "label", "group", "effort", "score",
    "duration", "duration_lo", "duration_hi", "open_min", "close_min", "closed_days", "hours_source",
    "golden_start", "golden_end", "confidence", "conf_m1", "conf_m2", "conf_m3",
    "n_checkins", "n_users", "n_visits", "one_time_share", "hour_profile", "visit_hist",
]


def next_version(model_dir: Path) -> str:
    nums = [int(p.name[1:]) for p in model_dir.glob("v*") if p.name[1:].isdigit()]
    return f"v{max(nums, default=0) + 1}"


def _round_to(x: np.ndarray, step: int) -> np.ndarray:
    return np.round(np.asarray(x, dtype=float) / step) * step


def visit_histograms(n_venues: int, visits: pd.DataFrame) -> np.ndarray:
    """Visits per venue in 20-minute bins: 0-20, ..., 220-240, 240+ (Figma D2)."""
    bins = len(VISIT_BIN_EDGES)
    b = np.minimum(visits["dwell"].to_numpy() // VISIT_BIN_MIN, bins - 1).astype(np.int64)
    flat = visits["venue_idx"].to_numpy().astype(np.int64) * bins + b
    return np.bincount(flat, minlength=n_venues * bins).reshape(n_venues, bins)


def one_time_share(n_venues: int, checkins: pd.DataFrame) -> np.ndarray:
    """Share of a venue's users who checked in there exactly once (0 without check-ins)."""
    per_user = checkins.groupby(["venue_idx", "user"]).size()
    share = (per_user == 1).groupby(level=0).mean()
    return share.reindex(np.arange(n_venues)).fillna(0).to_numpy()


def batch_infer(
    venues: pd.DataFrame, checkins: pd.DataFrame, visits: pd.DataFrame,
    m1: M1Popularity, m2: M2HourProfile, m3: M3VisitLength, opening: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Attribute table of every candidate place in the served cities, plus run statistics."""
    pop = m1.predict(venues, checkins)
    keep = venues["group"].notna().to_numpy() & venues["city"].isin(SUPPORTED_CITIES).to_numpy()
    idx = np.flatnonzero(keep)
    rows = venues.iloc[idx].copy()
    groups = rows["group"].to_numpy()
    everything = pd.Series(True, index=checkins.index)

    # M2: hour profile. Venues with little data lean on the ward / city / category prior.
    alpha = m2.alpha(rows, m2._hist(checkins, venues, everything)[idx])
    profile = circular_smooth(alpha, m2.width)
    profile /= profile.sum(1, keepdims=True)
    start_h, run_h = hour_windows(profile)

    # M3: visit length for an arrival in the busiest hour
    q = m3.predict_venues(venues, visits, idx, profile.argmax(1))
    known = rows["label"].isin(m3.labels or []).to_numpy()
    prior = np.array([fallback_duration(g) for g in groups])
    q = np.where(known[:, None], q, prior[:, None] * np.array([0.7, 1.0, 1.4]))
    duration = np.clip(_round_to(q[:, 1], 5), 15, 240)
    rows["duration"] = duration.astype(int)
    rows["duration_lo"] = np.clip(_round_to(q[:, 0], 5), 10, duration).astype(int)
    rows["duration_hi"] = np.clip(_round_to(q[:, 2], 5), duration, 300).astype(int)

    # Opening window. Check-ins mark arrivals, so the estimated closing time is the
    # last busy arrival hour plus one visit. Crawled hours replace the estimate.
    open_est = start_h * 60
    close_est = np.minimum((start_h + run_h) * 60 + np.minimum(_round_to(duration, 30), 120), open_est + 24 * 60)
    open_min, close_min = open_est.astype(float), close_est.astype(float)
    closed_days = np.full(len(rows), "[]", dtype=object)
    crawled = np.zeros(len(rows), dtype=bool)
    info: dict = {}
    if opening is not None and len(opening):
        real = opening.drop_duplicates("venue").set_index("venue").reindex(rows["venue"].to_numpy())
        crawled = real["open_min"].notna().to_numpy()
        open_min[crawled] = real["open_min"].to_numpy(dtype=float)[crawled]
        close_min[crawled] = real["close_min"].to_numpy(dtype=float)[crawled]
        closed_days[crawled] = real["closed_days"].to_numpy()[crawled]
        if crawled.any():  # how far the check-in estimate is from the real hours
            info["hours_eval"] = {
                "n": int(crawled.sum()),
                "open_mae_min": float(np.abs(open_est - open_min)[crawled].mean()),
                "close_mae_min": float(np.abs(close_est - close_min)[crawled].mean()),
            }
    rows["open_min"], rows["close_min"] = open_min.astype(int), close_min.astype(int)
    rows["closed_days"] = closed_days
    rows["hours_source"] = np.where(crawled, "crawl", "estimated")

    # Best time to visit (Figma T2): calm open hours; busiest hours for food and nightlife
    best = best_starts(profile, groups, open_min, close_min, duration)
    rows["golden_start"] = (best * 60).astype(int)
    rows["golden_end"] = rows["golden_start"] + BEST_MINUTES

    # Confidence, one per model
    best_ok, window_ok = m2.stability(alpha, groups, open_min, close_min, duration)
    n_visits = np.bincount(visits["venue_idx"].to_numpy(), minlength=len(venues))[idx]
    spread = (rows["duration_hi"] - rows["duration_lo"]).to_numpy() / duration
    rows["conf_m1"] = level(rows["n_users"].to_numpy(), 20, 5)
    rows["conf_m2"] = level(best_ok, STABLE_HIGH, STABLE_MEDIUM)
    rows["conf_m3"] = np.where(
        n_visits >= 20, "high", np.where((n_visits >= 5) | (known & (spread <= 0.6)), "medium", "low")
    )
    # `confidence` keeps its meaning for the planner: can the opening window be trusted?
    rows["confidence"] = np.where(crawled, "high", level(window_ok, STABLE_HIGH, STABLE_MEDIUM))

    # S_i: rank of predicted popularity among candidates of the same city -> [1, 100]
    rows["pop_pred"] = pop[idx]
    pct = rows.groupby("city")["pop_pred"].rank(pct=True, method="average")
    rows["score"] = np.round(1 + 99 * (pct - pct.min()) / max(1 - pct.min(), 1e-9)).astype(int).clip(1, 100)
    rows["hour_profile"] = [json.dumps(np.round(p, 4).tolist()) for p in profile]
    rows["n_visits"] = n_visits
    rows["visit_hist"] = [json.dumps(h.tolist()) for h in visit_histograms(len(venues), visits)[idx]]
    rows["one_time_share"] = np.round(one_time_share(len(venues), checkins)[idx], 3)

    info["confidence"] = {
        name: {city: g.value_counts().to_dict() for city, g in rows.groupby("city")[col]}
        for name, col in (("m1", "conf_m1"), ("m2", "conf_m2"), ("m3", "conf_m3"), ("window", "confidence"))
    }
    info["hours_source"] = rows["hours_source"].value_counts().to_dict()
    return rows[ATTRIBUTE_COLUMNS].reset_index(drop=True), info


def load_candidates(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Venues of the five candidate groups and their check-ins, re-indexed compactly.

    Training only ever looks at candidate places, so dropping homes, offices,
    stations... up front keeps the SEA-wide arrays small.
    """
    venues = pd.read_parquet(processed / "venues.parquet")
    checkins = pd.read_parquet(processed / "checkins.parquet")
    visits = pd.read_parquet(processed / "visits.parquet")
    cand = venues["group"].notna().to_numpy()
    remap = np.full(len(venues), -1, dtype=np.int32)
    remap[cand] = np.arange(int(cand.sum()), dtype=np.int32)
    venues = venues[cand].reset_index(drop=True)
    checkins = checkins[cand[checkins["venue_idx"].to_numpy()]].reset_index(drop=True)
    checkins["venue_idx"] = remap[checkins["venue_idx"].to_numpy()]
    visits = visits[cand[visits["venue_idx"].to_numpy()]].reset_index(drop=True)
    visits["venue_idx"] = remap[visits["venue_idx"].to_numpy()]
    return venues, checkins, visits


def train_all(
    processed: Path, model_dir: Path, version: str | None = None, source: str = "dataset", status: StatusFn | None = None
) -> dict:
    say = status or (lambda m, s, i=None: log.info("%s: %s %s", m, s, i or ""))
    version = version or next_version(model_dir)
    out = model_dir / version
    out.mkdir(parents=True, exist_ok=True)
    venues, checkins, visits = load_candidates(processed)
    say("pipeline", "loaded", {"venues": len(venues), "checkins": len(checkins), "visits": len(visits)})
    metrics: dict[str, dict] = {}
    t0 = time.perf_counter()

    say("m1", "training", None)
    m1 = M1Popularity()
    metrics["m1"] = m1.fit(venues, checkins)
    m1.save(out)
    say("m1", "trained", metrics["m1"])

    say("m2", "training", None)
    m2 = M2HourProfile()
    metrics["m2"] = m2.fit(venues, checkins)
    m2.save(out)
    say("m2", "trained", metrics["m2"])

    say("m3", "training", None)
    m3 = M3VisitLength()
    metrics["m3"] = m3.fit(venues, visits)
    m3.save(out)
    say("m3", "trained", metrics["m3"])

    say("pipeline", "inferring", None)
    hours_file = processed / preprocess.HOURS_TABLE
    opening = pd.read_parquet(hours_file) if hours_file.exists() else None
    attrs, info = batch_infer(venues, checkins, visits, m1, m2, m3, opening)
    attrs.to_parquet(out / "attributes.parquet", index=False)
    if "hours_eval" in info:
        metrics["m2"]["hours_eval"] = info.pop("hours_eval")
    quality_file = processed / preprocess.QUALITY_FILE
    # Run summary for the data and models screens (Figma D1 / D3). It lives under
    # metrics because that is what the API returns for a version.
    metrics["summary"] = {
        "visit_bin_edges": VISIT_BIN_EDGES,
        "data_quality": json.loads(quality_file.read_text()) if quality_file.exists() else {},
        **info,
    }
    stats = pd.read_parquet(processed / "country_stats.parquet")
    stats.to_parquet(out / "country_stats.parquet", index=False)
    meta = {
        "version": version,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.perf_counter() - t0, 1),
        "metrics": _clean(metrics),
        "places": int(len(attrs)),
        "places_by_city": attrs["city"].value_counts().to_dict(),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    say("pipeline", "done", meta)
    return meta


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    if isinstance(obj, (np.floating, np.integer)):
        return _clean(obj.item())
    return obj


def run(
    raw_dir: Path, work_dir: Path, model_dir: Path, source: str = "dataset", status: StatusFn | None = None,
    version: str | None = None,
) -> dict:
    processed = work_dir / ("processed" if source == "dataset" else "processed_sample")
    say = status or (lambda m, s, i=None: log.info("%s: %s %s", m, s, i or ""))
    preprocess.run(raw_dir, processed, status=lambda msg: say("pipeline", "preprocessing", {"message": msg}))
    return train_all(processed, model_dir, version=version, source=source, status=status)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--work", type=Path, default=Path("data"))
    ap.add_argument("--models", type=Path, default=Path("data/models"))
    ap.add_argument("--sample", action="store_true", help="generate and use the synthetic sample")
    ap.add_argument("--version")
    args = ap.parse_args()
    raw, source = args.raw, "dataset"
    if args.sample:
        from .sample import write_sample

        raw = args.work / "sample_raw"
        shutil.rmtree(raw, ignore_errors=True)
        write_sample(raw)
        source = "synthetic-sample"
    meta = run(raw, args.work, args.models, source=source, version=args.version)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()

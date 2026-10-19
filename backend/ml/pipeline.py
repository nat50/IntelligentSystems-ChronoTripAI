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
from .models import M1Popularity, M2HourProfile, M3VisitLength, fallback_duration, golden_window, hour_window

log = logging.getLogger(__name__)

MODELS = ("m1", "m2", "m3")
StatusFn = Callable[[str, str, dict | None], None]  # (model or "pipeline", status, info)


def confidence(n_checkins: np.ndarray) -> np.ndarray:
    return np.where(n_checkins >= 30, "high", np.where(n_checkins >= 10, "medium", "low"))


def next_version(model_dir: Path) -> str:
    nums = [int(p.name[1:]) for p in model_dir.glob("v*") if p.name[1:].isdigit()]
    return f"v{max(nums, default=0) + 1}"


def batch_infer(
    venues: pd.DataFrame, checkins: pd.DataFrame, m1: M1Popularity, m2: M2HourProfile, m3: M3VisitLength
) -> pd.DataFrame:
    pop = m1.predict(venues, checkins)
    conf = confidence(venues["n_checkins"].to_numpy())
    profiles = m2.profiles(venues, checkins, conf == "low")
    keep = venues["group"].notna().to_numpy() & venues["city"].isin(SUPPORTED_CITIES).to_numpy()

    rows = venues[keep].copy()
    idx = np.flatnonzero(keep)
    windows = [hour_window(profiles[i]) for i in idx]
    golden = [golden_window(profiles[i]) for i in idx]
    rows["open_min"] = [w[0] for w in windows]
    rows["close_min"] = [w[1] for w in windows]
    rows["golden_start"] = [g[0] for g in golden]
    rows["golden_end"] = [g[1] for g in golden]
    dur = m3.predict_venues(rows.reset_index(drop=True), (rows["golden_start"].to_numpy() // 60) % 24)
    known = rows["label"].isin(m3.labels or []).to_numpy()
    dur = np.where(known, dur, [fallback_duration(g) for g in rows["group"]])
    rows["duration"] = (np.clip(np.round(dur / 5) * 5, 15, 240)).astype(int)
    # S_i: rank of predicted popularity among candidates of the same city -> [1, 100]
    rows["pop_pred"] = pop[idx]
    pct = rows.groupby("city")["pop_pred"].rank(pct=True, method="average")
    rows["score"] = np.round(1 + 99 * (pct - pct.min()) / max(1 - pct.min(), 1e-9)).astype(int).clip(1, 100)
    rows["confidence"] = conf[idx]
    rows["hour_profile"] = [json.dumps(np.round(profiles[i], 4).tolist()) for i in idx]
    cols = [
        "venue", "city", "ward", "lat", "lon", "category", "label", "group", "effort", "score", "duration",
        "open_min", "close_min", "golden_start", "golden_end", "confidence", "n_checkins", "n_users", "hour_profile",
    ]
    return rows[cols].reset_index(drop=True)


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
    attrs = batch_infer(venues, checkins, m1, m2, m3)
    attrs.to_parquet(out / "attributes.parquet", index=False)
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

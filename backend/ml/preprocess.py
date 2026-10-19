"""Stream the raw LBSN2Vec++ files into compact Parquet tables (spec II.4).

Inputs (tab separated, no header), plain, .gz or inside a .zip:
  raw_POIs.txt                 venue_id, lat, lon, category name, country code
  raw_Checkins_anonymized.txt  user_id, venue_id, "Tue Apr 03 18:00:09 +0000 2012", tz offset (min)

Outputs in <processed>:
  venues.parquet         every SEA venue with check-ins (+ city, group, effort, label)
  checkins.parquet       SEA check-ins: user, venue_idx, local time, split
  visits.parquet         consecutive check-in pairs inside a session (for M3)
  country_stats.parquet  check-ins / users / venues per SEA country
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pandas as pd

from .categories import classify, fix_encoding
from .geo import SEA_COUNTRIES, SUPPORTED_CITIES, WARDS, assign_city, haversine_km

log = logging.getLogger(__name__)

POI_FILE = "raw_POIs.txt"
CHECKIN_FILE = "raw_Checkins_anonymized.txt"
SESSION_GAP_H = 8
TRAIN_END = pd.Timestamp("2013-09-01")  # train: 04/2012 - 08/2013
VAL_END = pd.Timestamp("2013-11-01")  # val: 09-10/2013, test: 11/2013 - 01/2014
SPLITS = ("train", "val", "test")
_MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def _zip_member(zf: zipfile.ZipFile, name: str) -> str | None:
    """Member whose file name matches, ignoring folders and letter case
    (the readme spells it both raw_Checkins_... and raw_checkins_...)."""
    want = name.lower()
    return next((n for n in zf.namelist() if Path(n).name.lower() == want), None)


def find_raw(raw_dir: Path, name: str) -> Path | None:
    if not raw_dir.exists():
        return None
    lowered = {p.name.lower(): p for p in raw_dir.iterdir() if p.is_file()}
    for cand in (name, name + ".gz"):
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    for z in sorted(raw_dir.glob("*.zip")):
        try:
            with zipfile.ZipFile(z) as zf:
                if _zip_member(zf, name):
                    return z
        except zipfile.BadZipFile:
            log.warning("skipping unreadable zip %s", z)
    return None


def _open_text(path: Path, name: str) -> io.TextIOBase:
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    if path.suffix == ".zip":
        zf = zipfile.ZipFile(path)
        return io.TextIOWrapper(zf.open(_zip_member(zf, name)), encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def _read_chunks(path: Path, name: str, names: list[str], dtype: dict, chunksize: int) -> Iterator[pd.DataFrame]:
    with _open_text(path, name) as fh:
        yield from pd.read_csv(
            fh,
            sep="\t",
            header=None,
            names=names,
            dtype=dtype,
            quoting=csv.QUOTE_NONE,
            on_bad_lines="skip",
            chunksize=chunksize,
        )


def parse_utc(s: pd.Series) -> pd.Series:
    """Fast parser for 'Tue Apr 03 18:00:09 +0000 2012'; malformed -> NaT."""
    s = s.astype("string")
    ok = s.str.len().eq(30) & s.str[20:25].eq("+0000")
    month = s.str[4:7].map(_MONTHS)
    iso = s.str[26:30] + "-" + month.astype("Int64").astype("string").str.zfill(2) + "-" + s.str[8:10] + " " + s.str[11:19]
    out = pd.to_datetime(iso.where(ok), format="%Y-%m-%d %H:%M:%S", errors="coerce")
    if len(s) and out.isna().mean() > 0.5:
        # Unexpected layout: let pandas infer it, then drop the timezone (it is UTC)
        log.warning("fast UTC parser failed on %.0f%% of rows, falling back", 100 * out.isna().mean())
        out = pd.to_datetime(s, errors="coerce", utc=True, format="mixed").dt.tz_localize(None)
    return out


def load_venues(raw_dir: Path, chunksize: int = 2_000_000) -> pd.DataFrame:
    path = find_raw(raw_dir, POI_FILE)
    if path is None:
        raise FileNotFoundError(f"{POI_FILE} not found in {raw_dir}")
    parts = []
    names = ["venue", "lat", "lon", "category", "cc"]
    for chunk in _read_chunks(path, POI_FILE, names, {"venue": str, "category": str, "cc": str}, chunksize):
        chunk = chunk[chunk["cc"].isin(SEA_COUNTRIES)].assign(
            lat=lambda d: pd.to_numeric(d["lat"], errors="coerce"),
            lon=lambda d: pd.to_numeric(d["lon"], errors="coerce"),
        )
        parts.append(chunk.dropna(subset=["lat", "lon", "venue"]))
    venues = pd.concat(parts, ignore_index=True).drop_duplicates("venue")
    venues["category"] = venues["category"].fillna("").map(fix_encoding)
    log.info("SEA venues: %d", len(venues))
    return venues


def load_checkins(
    raw_dir: Path, venues: pd.DataFrame, chunksize: int = 5_000_000, progress: Callable[[str], None] | None = None
) -> pd.DataFrame:
    path = find_raw(raw_dir, CHECKIN_FILE)
    if path is None:
        raise FileNotFoundError(f"{CHECKIN_FILE} not found in {raw_dir}")
    venue_index = pd.Index(venues["venue"])
    parts, total = [], 0
    names = ["user", "venue", "utc", "offset"]
    for chunk in _read_chunks(path, CHECKIN_FILE, names, {"venue": str, "utc": str}, chunksize):
        total += len(chunk)
        idx = venue_index.get_indexer(chunk["venue"])
        chunk = chunk.assign(venue_idx=idx)[idx >= 0]
        utc = parse_utc(chunk["utc"])
        offset = pd.to_numeric(chunk["offset"], errors="coerce")
        user = pd.to_numeric(chunk["user"], errors="coerce")
        ok = utc.notna() & offset.notna() & user.notna() & offset.abs().le(14 * 60)
        local = utc[ok] + pd.to_timedelta(offset[ok], unit="m")
        parts.append(
            pd.DataFrame(
                {
                    "user": user[ok].astype(np.int64).to_numpy(),
                    "venue_idx": chunk.loc[ok, "venue_idx"].astype(np.int32).to_numpy(),
                    "local": local.to_numpy(dtype="datetime64[s]"),
                }
            )
        )
        msg = f"Read {total:,} check-ins, kept {sum(len(p) for p in parts):,} in Southeast Asia"
        (progress or log.info)(msg)
    out = pd.concat(parts, ignore_index=True)
    out["split"] = pd.Categorical(
        np.where(out["local"] < TRAIN_END, "train", np.where(out["local"] < VAL_END, "val", "test")),
        categories=list(SPLITS),
    )
    return out


def build_visits(checkins: pd.DataFrame, venues: pd.DataFrame) -> pd.DataFrame:
    """Consecutive pairs in a user's session (gap <= 8 h) -> dwell-time proxy (M3)."""
    df = checkins.sort_values(["user", "local"], kind="stable")
    user = df["user"].to_numpy()
    t = df["local"].to_numpy().astype("datetime64[s]").astype(np.int64)
    v = df["venue_idx"].to_numpy()
    same = (user[1:] == user[:-1]) & (t[1:] - t[:-1] <= SESSION_GAP_H * 3600) & (v[1:] != v[:-1])
    a = np.flatnonzero(same)
    lat, lon = venues["lat"].to_numpy(), venues["lon"].to_numpy()
    dist = haversine_km(lat[v[a]], lon[v[a]], lat[v[a + 1]], lon[v[a + 1]])
    travel_min = dist / 20.0 * 60.0 + 3.0  # urban door-to-door estimate
    dwell = (t[a + 1] - t[a]) / 60.0 - travel_min
    keep = (dwell >= 5) & (dwell <= 360) & (dist <= 30)
    a = a[keep]
    local = df["local"].to_numpy()[a]
    return pd.DataFrame(
        {
            "venue_idx": v[a].astype(np.int32),
            "local": local,
            "dwell": dwell[keep].astype(np.float32),
            "split": df["split"].to_numpy()[a],
        }
    )


def enrich_venues(venues: pd.DataFrame, checkins: pd.DataFrame) -> pd.DataFrame:
    venues = venues.reset_index(drop=True).copy()
    counts = checkins.groupby("venue_idx").agg(n_checkins=("user", "size"), n_users=("user", "nunique"))
    venues = venues.join(counts, how="left")
    venues[["n_checkins", "n_users"]] = venues[["n_checkins", "n_users"]].fillna(0).astype(np.int64)
    # classify each distinct category once (a few hundred), not each venue (millions)
    cats = venues["category"].astype("category")
    table = [classify(c) for c in cats.cat.categories]
    codes = cats.cat.codes.to_numpy()
    venues["group"] = pd.Series([t[0] for t in table], dtype=object).to_numpy()[codes]
    venues["effort"] = np.array([t[1] for t in table], dtype=np.int8)[codes]
    venues["label"] = pd.Series([t[2] for t in table], dtype=object).to_numpy()[codes]
    venues["city"] = assign_city(venues["lat"].to_numpy(), venues["lon"].to_numpy())
    venues["ward"] = ward_labels(venues)
    return venues


def ward_labels(venues: pd.DataFrame) -> np.ndarray:
    """Ward labels for the supported cities (vectorised), empty elsewhere."""
    out = np.full(len(venues), "", dtype=object)
    for city in SUPPORTED_CITIES:
        mask = (venues["city"] == city).to_numpy()
        if not mask.any():
            continue
        wards = [(w, wl, wn) for c, w, wl, wn in WARDS if c == city]
        lat, lon = venues.loc[mask, "lat"].to_numpy(), venues.loc[mask, "lon"].to_numpy()
        d = np.stack([haversine_km(lat, lon, wl, wn) for _, wl, wn in wards], axis=1)
        k = d.argmin(1)
        names = np.array([w for w, _, _ in wards], dtype=object)[k]
        out[mask] = np.where(d[np.arange(len(k)), k] <= 5.0, names, city)
    return out


def country_stats(checkins: pd.DataFrame, venues: pd.DataFrame) -> pd.DataFrame:
    cc = venues["cc"].to_numpy()[checkins["venue_idx"].to_numpy()]
    df = pd.DataFrame({"country": cc, "user": checkins["user"].to_numpy(), "venue": checkins["venue_idx"].to_numpy()})
    stats = df.groupby("country").agg(checkins=("user", "size"), users=("user", "nunique"), venues=("venue", "nunique"))
    return stats.reset_index().sort_values("checkins", ascending=False)


def run(raw_dir: Path, out_dir: Path, status: Callable[[str], None] | None = None) -> dict:
    say = status or log.info
    out_dir.mkdir(parents=True, exist_ok=True)
    say("Reading POIs")
    venues = load_venues(raw_dir)
    say("Streaming check-ins")
    checkins = load_checkins(raw_dir, venues, progress=say)
    # keep only venues that were checked in, re-index compactly
    used = np.unique(checkins["venue_idx"].to_numpy())
    remap = np.full(len(venues), -1, dtype=np.int32)
    remap[used] = np.arange(len(used), dtype=np.int32)
    venues = venues.iloc[used].reset_index(drop=True)
    checkins["venue_idx"] = remap[checkins["venue_idx"].to_numpy()]
    say(f"Classifying {len(venues):,} venues")
    venues = enrich_venues(venues, checkins)
    say("Building visit sessions")
    visits = build_visits(checkins, venues)
    # M3 only needs dwell times at candidate places
    visits = visits[venues["group"].notna().to_numpy()[visits["venue_idx"].to_numpy()]].reset_index(drop=True)
    stats = country_stats(checkins, venues)

    venues.to_parquet(out_dir / "venues.parquet", index=False)
    checkins.to_parquet(out_dir / "checkins.parquet", index=False)
    visits.to_parquet(out_dir / "visits.parquet", index=False)
    stats.to_parquet(out_dir / "country_stats.parquet", index=False)
    summary = {
        "venues": int(len(venues)),
        "candidates": int(venues["group"].notna().sum()),
        "checkins": int(len(checkins)),
        "visits": int(len(visits)),
        "split_counts": checkins["split"].value_counts().to_dict(),
    }
    say(f"Preprocessed {summary['checkins']:,} check-ins at {summary['venues']:,} venues")
    return summary

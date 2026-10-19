"""Model versions: load a trained version into the database and activate it (FR-06)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import orm
from ..config import get_settings

log = logging.getLogger(__name__)

# Spec Table 2, measured directly on the raw files. Shown until a real
# preprocessing run replaces them.
MEASURED_STATS = [
    ("ID", 7_765_315, 361_193, 1_198_611),
    ("MY", 4_926_144, 127_390, 493_453),
    ("TH", 2_633_608, 82_765, 353_444),
    ("PH", 1_998_063, 60_197, 219_097),
    ("SG", 871_619, 41_262, 75_549),
    ("VN", 48_357, 4_761, 16_519),
]


def seed_country_stats(s: Session) -> None:
    if s.scalar(select(orm.CountryStat).limit(1)) is None:
        s.add_all(
            orm.CountryStat(country=c, checkins=a, users=b, venues=v, source="measured")
            for c, a, b, v in MEASURED_STATS
        )
        s.commit()


def active_version(s: Session) -> str | None:
    return s.scalar(select(orm.ModelVersion.version).where(orm.ModelVersion.is_active))


def register_version(s: Session, version_dir: Path) -> orm.ModelVersion:
    """Load attributes.parquet of a trained version into the places table."""
    meta = json.loads((version_dir / "meta.json").read_text())
    version = meta["version"]
    attrs = pd.read_parquet(version_dir / "attributes.parquet")
    s.execute(delete(orm.Place).where(orm.Place.version == version))
    records = attrs.assign(version=version).to_dict("records")
    for r in records:
        r["hour_profile"] = json.loads(r["hour_profile"])
    s.bulk_insert_mappings(orm.Place, records)
    mv = s.get(orm.ModelVersion, version) or orm.ModelVersion(version=version)
    mv.source = meta["source"]
    mv.created_at = datetime.fromisoformat(meta["created_at"])
    mv.metrics = meta["metrics"]
    mv.places = len(records)
    s.add(mv)
    if meta["source"] == "dataset" and (version_dir / "country_stats.parquet").exists():
        stats = pd.read_parquet(version_dir / "country_stats.parquet")
        s.execute(delete(orm.CountryStat))
        s.add_all(
            orm.CountryStat(country=r.country, checkins=int(r.checkins), users=int(r.users), venues=int(r.venues), source="dataset")
            for r in stats.itertuples()
        )
    s.commit()
    log.info("registered %s with %d places", version, len(records))
    return mv


def activate(s: Session, version: str) -> orm.ModelVersion:
    mv = s.get(orm.ModelVersion, version)
    if mv is None:
        raise KeyError(version)
    s.execute(update(orm.ModelVersion).values(is_active=False))
    mv.is_active = True
    s.commit()
    return mv


def sync_from_disk(s: Session) -> None:
    """Register versions found in data/models; activate the newest if none is active."""
    model_dir = get_settings().model_dir
    known = set(s.scalars(select(orm.ModelVersion.version)))
    for d in sorted(model_dir.glob("*/meta.json")):
        if d.parent.name not in known and (d.parent / "attributes.parquet").exists():
            register_version(s, d.parent)
    if active_version(s) is None:
        latest = s.scalar(select(orm.ModelVersion).order_by(orm.ModelVersion.created_at.desc()))
        if latest:
            activate(s, latest.version)

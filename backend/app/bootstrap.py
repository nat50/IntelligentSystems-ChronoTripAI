"""First-run setup: download the LBSN2Vec++ dataset (if missing), preprocess it,
train M1-M3, load the predicted attributes and activate that model version.

    python -m app.bootstrap                  # real dataset, downloaded automatically
    python -m app.bootstrap --skip-download  # use files already in data/raw
    python -m app.bootstrap --sample         # synthetic sample (tests / offline)
"""

from __future__ import annotations

import argparse
import logging
import shutil

from sqlalchemy import select

from ml import pipeline
from ml.download import download
from ml.sample import write_sample

from . import orm
from .config import get_settings
from .db import SessionLocal, init_db
from .services.training import dataset_found
from .services.versions import activate, register_version, seed_country_stats, sync_from_disk

log = logging.getLogger(__name__)


def run(sample: bool = False, allow_download: bool = True, force: bool = False) -> str | None:
    settings = get_settings()
    init_db()
    with SessionLocal() as s:
        seed_country_stats(s)
        sync_from_disk(s)
        if not force and s.scalar(select(orm.ModelVersion).limit(1)) is not None:
            log.info("A model version already exists; nothing to do (use --force to train another).")
            return None

    if sample:
        raw, source = settings.data_dir / "sample_raw", "synthetic-sample"
        shutil.rmtree(raw, ignore_errors=True)
        write_sample(raw)
    else:
        raw, source = settings.raw_dir, "dataset"
        if not dataset_found():
            if not allow_download:
                raise SystemExit(f"Dataset not found in {raw}. Run without --skip-download or use --sample.")
            log.info("Downloading LBSN2Vec++ (2.68 GB) into %s", raw)
            last = [-1]

            def show(p: dict) -> None:
                if p["stage"] == "downloading":
                    pct = int(100 * p["done"] / p["total"])
                    if pct != last[0] and pct % 5 == 0:
                        last[0] = pct
                        log.info("download %d%% (%.1f MB/s)", pct, p["speed"] / 1e6)

            download(raw, show)

    meta = pipeline.run(raw, settings.data_dir, settings.model_dir, source=source)
    with SessionLocal() as s:
        register_version(s, settings.model_dir / meta["version"])
        activate(s, meta["version"])
    log.info("Activated %s (%s, %d places)", meta["version"], source, meta["places"])
    return meta["version"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="train on the synthetic sample instead")
    ap.add_argument("--skip-download", action="store_true", help="never download; fail if files are missing")
    ap.add_argument("--force", action="store_true", help="train a new version even if one exists")
    args = ap.parse_args()
    run(sample=args.sample, allow_download=not args.skip_download, force=args.force)


if __name__ == "__main__":
    main()

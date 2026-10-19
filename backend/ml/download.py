"""Download the LBSN2Vec++ dataset from 4TU.ResearchData.

    python -m ml.download [--dest data/raw]

The file list, download links and MD5 checksums come from the 4TU API, so
nothing is hard-coded except the dataset id. Downloads resume after an
interruption (HTTP Range) and are verified against the published MD5. The zip
is not extracted: preprocessing streams the files straight out of it.

Dataset: Dingqi Yang et al., "LBSN2Vec++: Heterogeneous Hypergraph Embedding for
Location-Based Social Networks", IEEE TKDE 2020 / WWW'19. Licence CC BY 4.0.
DOI 10.4121/15112308.v1
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

ARTICLE_ID = "882bd9c5-5821-48b6-9b35-5c9551dd04ca"
FILES_API = f"https://data.4tu.nl/v2/articles/{ARTICLE_ID}/files"
CHUNK = 1 << 20

ProgressFn = Callable[[dict], None]


@dataclass
class RemoteFile:
    name: str
    size: int
    url: str
    md5: str


def list_files(client: httpx.Client) -> list[RemoteFile]:
    r = client.get(FILES_API, timeout=30)
    r.raise_for_status()
    return [
        RemoteFile(f["name"], int(f["size"]), f["download_url"], f.get("computed_md5") or f.get("supplied_md5") or "")
        for f in r.json()
    ]


def md5_of(path: Path, progress: ProgressFn | None = None) -> str:
    h = hashlib.md5()
    total, done = path.stat().st_size, 0
    with open(path, "rb") as fh:
        while block := fh.read(CHUNK * 8):
            h.update(block)
            done += len(block)
            if progress:
                progress({"stage": "verifying", "done": done, "total": total})
    return h.hexdigest()


def _fetch(client: httpx.Client, rf: RemoteFile, dest: Path, progress: ProgressFn | None) -> Path:
    final = dest / rf.name
    part = dest / (rf.name + ".part")
    if final.exists() and final.stat().st_size == rf.size:
        if not rf.md5 or md5_of(final, progress) == rf.md5:
            return final
        final.unlink()  # corrupted, download again
    for attempt in range(1, 11):
        have = part.stat().st_size if part.exists() else 0
        if have > rf.size:
            part.unlink()
            have = 0
        if have == rf.size:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with client.stream("GET", rf.url, headers=headers, timeout=httpx.Timeout(60, read=120)) as r:
                if r.status_code == 200 and have:  # server ignored Range: start over
                    have = 0
                    part.unlink(missing_ok=True)
                elif r.status_code not in (200, 206):
                    r.raise_for_status()
                started, start_bytes = time.monotonic(), have
                with open(part, "ab") as fh:
                    for block in r.iter_bytes(CHUNK):
                        fh.write(block)
                        have += len(block)
                        if progress:
                            elapsed = max(time.monotonic() - started, 1e-6)
                            speed = (have - start_bytes) / elapsed
                            progress(
                                {
                                    "stage": "downloading", "file": rf.name, "done": have, "total": rf.size,
                                    "speed": speed, "eta": (rf.size - have) / speed if speed > 0 else None,
                                }
                            )
            if have >= rf.size:
                break
        except (httpx.HTTPError, OSError) as exc:
            if progress:
                progress({"stage": "retrying", "file": rf.name, "attempt": attempt, "error": str(exc)})
            time.sleep(min(30, 2 * attempt))
    else:
        raise RuntimeError(f"Could not download {rf.name} after 10 attempts")
    if rf.md5:
        got = md5_of(part, progress)
        if got != rf.md5:
            part.unlink()
            raise RuntimeError(f"MD5 mismatch for {rf.name}: expected {rf.md5}, got {got}. The partial file was removed.")
    part.replace(final)
    return final


def download(dest: Path, progress: ProgressFn | None = None) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, headers={"User-Agent": "ChronoTrip-AI/1.0 (dataset download)"}) as client:
        files = list_files(client)
        # small files first so the readme is there early
        return [_fetch(client, rf, dest, progress) for rf in sorted(files, key=lambda f: f.size)]


def preview(zip_path: Path, names=("raw_POIs.txt", "raw_Checkins_anonymized.txt"), lines: int = 3) -> dict[str, list[str]]:
    """First lines of the raw files inside the zip, to confirm the format."""
    out: dict[str, list[str]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        members = {Path(n).name.lower(): n for n in zf.namelist()}
        for name in names:
            member = members.get(name.lower())
            if member is None:
                out[name] = ["<missing>"]
                continue
            with io.TextIOWrapper(zf.open(member), encoding="utf-8", errors="replace") as fh:
                out[name] = [fh.readline().rstrip("\n") for _ in range(lines)]
    return out


def _cli_progress() -> ProgressFn:
    last = [0.0]

    def show(p: dict) -> None:
        now = time.monotonic()
        if now - last[0] < 0.5 and p.get("done") != p.get("total"):
            return
        last[0] = now
        if p["stage"] == "downloading":
            pct = 100 * p["done"] / p["total"]
            eta = f"{p['eta'] / 60:.1f} min" if p.get("eta") else "?"
            sys.stdout.write(
                f"\r{p['file']}: {p['done'] / 1e9:.2f}/{p['total'] / 1e9:.2f} GB ({pct:.1f}%) "
                f"{p['speed'] / 1e6:.1f} MB/s, ETA {eta}   "
            )
        elif p["stage"] == "verifying":
            sys.stdout.write(f"\rVerifying MD5: {100 * p['done'] / p['total']:.0f}%                               ")
        elif p["stage"] == "retrying":
            sys.stdout.write(f"\nRetry {p['attempt']} for {p['file']}: {p['error']}\n")
        sys.stdout.flush()

    return show


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", type=Path, default=None, help="default: <data_dir>/raw")
    args = ap.parse_args()
    if args.dest is None:
        from app.config import get_settings

        args.dest = get_settings().raw_dir
    paths = download(args.dest, _cli_progress())
    print()
    for p in paths:
        print(f"OK {p} ({p.stat().st_size:,} bytes)")
    for z in (p for p in paths if p.suffix == ".zip"):
        for name, rows in preview(z).items():
            print(f"\n{name}:")
            for row in rows:
                print("  " + row.replace("\t", " | "))


if __name__ == "__main__":
    main()

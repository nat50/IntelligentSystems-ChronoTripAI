"""Real opening hours from OpenStreetMap (Figma D1: "Place details (web crawl)").

Check-ins only show when people arrive, so the opening window M2 derives from
them is an estimate. Where OpenStreetMap knows the hours of a place, those are
used instead and the estimate is kept only as a fallback.

    python -m ml.hours --raw data/raw      # crawl the served cities once (needs network)

The crawl is cached in <raw>/osm_hours.json; the pipeline only reads that file
and works without it. Matching rule (Figma D1, step 3): the nearest OSM place
of the same group within 100 m.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .categories import classify
from .geo import CITIES, CITY_RADIUS_KM, SUPPORTED_CITIES, haversine_km

log = logging.getLogger(__name__)

HOURS_FILE = "osm_hours.json"
MATCH_RADIUS_KM = 0.1
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OSM_KEYS = ("amenity", "tourism", "shop", "leisure", "historic")
DAYS = ("mo", "tu", "we", "th", "fr", "sa", "su")  # index = datetime.weekday()

# OSM tag values that the Foursquare category rules do not recognise as they are
_KIND_ALIASES = {
    "place_of_worship": "temple", "attraction": "landmark", "fast_food": "restaurant",
    "marketplace": "market", "nightclub": "night club", "viewpoint": "scenic lookout",
    "biergarten": "beer garden", "ice_cream": "ice cream", "food_court": "food court",
    "arts_centre": "arts", "books": "bookstore", "clothes": "clothing",
}
_TIME = r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}"
_RULE = re.compile(rf"^(?P<days>[a-z ,\-]*?)\s*(?P<times>{_TIME}(?:\s*,\s*{_TIME})*|off|closed)$")


def _minutes(clock: str) -> int:
    h, m = clock.split(":")
    return int(h) * 60 + int(m)


def _days(spec: str) -> list[int] | None:
    """'mo-fr,su' -> [0, 1, 2, 3, 4, 6]; None if it is not a plain weekday list."""
    spec = spec.replace(" ", "")
    if not spec:
        return list(range(7))
    out: list[int] = []
    for part in spec.split(","):
        if part == "ph":  # "Mo-Su,PH": public holidays are not modelled
            continue
        ends = part.split("-")
        if not 1 <= len(ends) <= 2 or any(e not in DAYS for e in ends):
            return None
        a, b = DAYS.index(ends[0]), DAYS.index(ends[-1])
        out += [d % 7 for d in range(a, b + 1 if b >= a else b + 8)]
    return out


def parse_opening_hours(text: str) -> dict | None:
    """The common part of the OSM opening_hours syntax -> one daily window.

    Returns {"open_min", "close_min", "closed_days"} with minutes since midnight
    (close_min > 1440 when the place closes after midnight) and closed weekdays
    (0 = Monday). A lunch break is ignored (earliest opening to latest closing),
    and when days differ the most common window is used. Anything outside this
    subset (months, sunrise, week numbers...) returns None: no real hours.
    """
    text = (text or "").strip().lower()
    if not text:
        return None
    if text.startswith("24/7"):
        return {"open_min": 0, "close_min": 24 * 60, "closed_days": []}
    text = re.sub(r"\b(mo|tu|we|th|fr|sa|su)[a-z]*\b", r"\1", text)  # "Mon", "Sun" -> "mo", "su"
    text = re.sub(r"(\d{1,2}:\d{2})\+", r"\1", text)  # "10:00-22:00+": open end, the stated time is used
    week: list[tuple[int, int] | None] = [None] * 7
    # rules are separated by ";", and often by "," before a new day list ("Mo-Th 08:00-22:00, Fr-Su ...")
    # (only after a time or "off", so "Mo-Su,PH 08:00-22:00" stays one rule)
    for rule in (r.strip() for r in re.split(r";|(?<=\d|f),\s*(?=(?:mo|tu|we|th|fr|sa|su|ph)\b)", text)):
        if not rule or rule.startswith("ph"):  # public holidays are not modelled
            continue
        m = _RULE.match(rule)
        days = _days(m["days"]) if m else None
        if days is None:
            return None
        window = None
        if m["times"] not in ("off", "closed"):
            spans = [[_minutes(c.strip()) for c in s.split("-")] for s in m["times"].split(",")]
            if any(a >= 24 * 60 or b > 24 * 60 for a, b in spans):
                return None
            window = (min(a for a, _ in spans), max(b if b > a else b + 24 * 60 for a, b in spans))
        for d in days:
            week[d] = window
    opened = [w for w in week if w is not None]
    if not opened:
        return None
    (open_min, close_min), _ = Counter(opened).most_common(1)[0]
    return {"open_min": open_min, "close_min": close_min, "closed_days": [d for d in range(7) if week[d] is None]}


def kind_group(kind: str) -> str | None:
    """Candidate group of an OSM place from its tag values ('cafe', 'museum', 'shop mall'...)."""
    words = [_KIND_ALIASES.get(w, w) for w in kind.lower().split()]
    return classify(" ".join(words).replace("_", " ").replace("shop ", "shopping "))[0]


def _overpass(query: str, timeout: float, rounds: int = 3) -> dict:
    """POST a query, trying each public Overpass server in turn; they are often busy (429 / 502 / 504)."""
    import httpx

    errors = []
    for attempt in range(rounds):
        for url in OVERPASS_URLS:
            try:
                r = httpx.post(url, data={"data": query}, timeout=timeout + 30, headers={"User-Agent": "chronotrip-hours"})
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{url}: {exc}")
                log.warning("Overpass %s failed (%s), trying the next server", url, exc)
        time.sleep(30 * (attempt + 1))
    raise RuntimeError("Every Overpass server failed:\n" + "\n".join(errors[-len(OVERPASS_URLS):]))


def fetch(raw_dir: Path, cities: tuple[str, ...] = SUPPORTED_CITIES, timeout: float = 180.0) -> Path:
    """Download every OSM place with opening hours around the served cities."""
    radius = int(CITY_RADIUS_KM * 1000)
    places = []
    for name, _, lat, lon in CITIES:
        if name not in cities:
            continue
        parts = "".join(f'nwr["opening_hours"]["{k}"](around:{radius},{lat},{lon});' for k in OSM_KEYS)
        query = f"[out:json][timeout:{int(timeout)}];({parts});out center tags;"
        for el in _overpass(query, timeout).get("elements", []):
            tags = el.get("tags", {})
            pos = el if "lat" in el else el.get("center", {})
            if "lat" not in pos:
                continue
            kind = " ".join(f"shop {tags[k]}" if k == "shop" else tags[k] for k in OSM_KEYS if k in tags)
            places.append({"lat": pos["lat"], "lon": pos["lon"], "kind": kind, "opening_hours": tags["opening_hours"]})
        log.info("%s: %d OSM places with opening hours so far", name, len(places))
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / HOURS_FILE
    out.write_text(json.dumps(places, ensure_ascii=False), encoding="utf-8")
    return out


def load(raw_dir: Path) -> pd.DataFrame | None:
    """Parsed crawl: lat, lon, group, open_min, close_min, closed_days. None without a crawl file."""
    path = raw_dir / HOURS_FILE
    if not path.exists():
        return None
    rows = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        hours = parse_opening_hours(item.get("opening_hours", ""))
        group = kind_group(item.get("kind", ""))
        if hours and group:
            rows.append({"lat": float(item["lat"]), "lon": float(item["lon"]), "group": group, **hours})
    return pd.DataFrame(rows, columns=["lat", "lon", "group", "open_min", "close_min", "closed_days"])


def match(venues: pd.DataFrame, osm: pd.DataFrame, chunk: int = 2000) -> pd.DataFrame:
    """Opening hours of each venue of a served city that has an OSM place of its group within 100 m."""
    v = venues[venues["group"].notna() & venues["city"].isin(SUPPORTED_CITIES)]
    found = []
    if len(v) and len(osm):
        o_lat, o_lon, o_group = osm["lat"].to_numpy(), osm["lon"].to_numpy(), osm["group"].to_numpy()
        for a in range(0, len(v), chunk):
            part = v.iloc[a : a + chunk]
            d = haversine_km(part["lat"].to_numpy()[:, None], part["lon"].to_numpy()[:, None], o_lat[None, :], o_lon[None, :])
            d[part["group"].to_numpy()[:, None] != o_group[None, :]] = np.inf
            k = d.argmin(1)
            hit = d[np.arange(len(part)), k] <= MATCH_RADIUS_KM
            near = osm.iloc[k[hit]]
            found.append(
                pd.DataFrame(
                    {
                        "venue": part["venue"].to_numpy()[hit],
                        "open_min": near["open_min"].to_numpy(),
                        "close_min": near["close_min"].to_numpy(),
                        "closed_days": [json.dumps(list(c)) for c in near["closed_days"]],
                    }
                )
            )
    cols = ["venue", "open_min", "close_min", "closed_days"]
    return pd.concat(found, ignore_index=True)[cols] if found else pd.DataFrame(columns=cols)


def prepare(raw_dir: Path, venues: pd.DataFrame) -> pd.DataFrame | None:
    osm = load(raw_dir)
    return None if osm is None else match(venues, osm)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    args = ap.parse_args()
    path = fetch(args.raw)
    parsed = load(args.raw)
    print(f"Saved {path}: {len(parsed)} places with usable opening hours")


if __name__ == "__main__":
    main()

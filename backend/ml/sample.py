"""Synthetic check-ins in the exact raw LBSN2Vec++ format.

Used by the tests and to bootstrap a working app before the real dataset
(2.68 GB) is downloaded. Everything trained on it is labelled
"synthetic-sample" in the API and the admin screen.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .geo import CITIES, SUPPORTED_CITIES, WARDS, haversine_km
from .hours import HOURS_FILE

# name, hour peaks [(centre, spread)], mean dwell (min), weight
CATALOG: list[tuple[str, list[tuple[float, float]], float, float]] = [
    ("Vietnamese Restaurant", [(12, 1.0), (19, 1.3)], 50, 3.0),
    ("Café", [(9, 1.5), (15, 2.0)], 60, 3.0),
    ("Coffee Shop", [(8, 1.5), (14, 2.5)], 55, 2.0),
    ("Bubble Tea Shop", [(15, 2.5)], 30, 1.0),
    ("Street Food Gathering", [(18.5, 1.8)], 40, 1.5),
    ("Seafood Restaurant", [(19, 1.4)], 70, 1.2),
    ("Museum", [(10, 1.4), (14.5, 1.5)], 85, 0.8),
    ("Art Gallery", [(11, 2.0), (16, 2.0)], 60, 0.5),
    ("Buddhist Temple", [(7.5, 1.5), (17, 1.5)], 45, 0.7),
    ("Church", [(7, 1.5), (17.5, 1.2)], 35, 0.5),
    ("Historic Site", [(9.5, 1.5), (15.5, 2.0)], 60, 0.6),
    ("Park", [(6.5, 1.2), (17.5, 1.5)], 50, 1.2),
    ("Plaza", [(19.5, 2.0)], 40, 0.6),
    ("Market", [(8, 1.5), (16, 2.0)], 60, 1.0),
    ("Night Market", [(20.5, 1.4)], 75, 0.6),
    ("Shopping Mall", [(15, 2.5), (19.5, 1.5)], 90, 1.5),
    ("Bookstore", [(16, 2.5)], 45, 0.4),
    ("Movie Theater", [(19.5, 2.0)], 140, 0.8),
    ("Theme Park", [(10.5, 2.0), (15, 2.0)], 180, 0.2),
    ("Zoo", [(9, 1.5)], 120, 0.2),
    ("Bar", [(21.5, 1.5)], 90, 0.8),
    ("Nightclub", [(23.5, 1.2)], 120, 0.3),
    ("Karaoke Bar", [(21, 1.5)], 120, 0.5),
    ("Beach", [(16.5, 2.0)], 120, 0.3),
    # not itinerary candidates, must be filtered out by preprocessing
    ("Home (private)", [(21, 2.0)], 300, 2.0),
    ("Office", [(9, 1.0), (13.5, 1.0)], 240, 2.0),
    ("University", [(9, 1.5)], 180, 0.8),
    ("Bus Station", [(7, 2.0), (17, 2.0)], 20, 0.6),
    ("Hotel", [(14, 3.0)], 300, 0.5),
]
# OSM-style tag value and opening hours of the categories that get crawled hours
# in the sample (same file format as ml.hours.fetch writes).
SAMPLE_HOURS: dict[str, tuple[str, str]] = {
    "Vietnamese Restaurant": ("restaurant", "Mo-Su 10:00-22:00"),
    "Café": ("cafe", "Mo-Su 07:00-22:00"),
    "Coffee Shop": ("cafe", "Mo-Su 06:30-21:30"),
    "Bubble Tea Shop": ("cafe", "Mo-Su 09:00-22:00"),
    "Street Food Gathering": ("fast_food", "Mo-Su 16:00-23:00"),
    "Seafood Restaurant": ("restaurant", "Mo-Su 16:00-23:00"),
    "Museum": ("museum", "Tu-Su 08:00-11:30,13:30-17:00"),
    "Art Gallery": ("gallery", "Tu-Su 09:00-18:00"),
    "Buddhist Temple": ("place_of_worship", "Mo-Su 06:00-19:00"),
    "Church": ("place_of_worship", "05:30-19:00"),
    "Historic Site": ("attraction", "Mo-Su 07:30-17:00; PH off"),
    "Park": ("park", "Mo-Su 05:00-22:00"),
    "Market": ("marketplace", "Mo-Su 06:00-18:00"),
    "Night Market": ("marketplace", "Mo-Su 18:00-23:30"),
    "Shopping Mall": ("shop mall", "Mo-Su 09:30-22:00"),
    "Bookstore": ("shop books", "Mo-Sa 08:00-21:30"),
    "Movie Theater": ("cinema", "Mo-Su 09:00-23:30"),
    "Theme Park": ("theme_park", "We-Mo 08:30-17:30"),
    "Zoo": ("zoo", "Mo-Su 07:00-18:30"),
    "Bar": ("bar", "Mo-Su 17:00-02:00"),
    "Nightclub": ("nightclub", "Tu-Su 21:00-03:00"),
}
HOURS_SHARE = 0.45  # share of those places that the crawl knows
OFFSETS = {"VN": 420, "TH": 420, "ID": 420, "KH": 420, "MY": 480, "SG": 480, "PH": 480}
USER_SHARE = {
    "Ho Chi Minh City": 0.16, "Hanoi": 0.10, "Jakarta": 0.18, "Kuala Lumpur": 0.12, "Bangkok": 0.10,
    "Manila": 0.07, "Singapore": 0.06, "Bandung": 0.04, "Surabaya": 0.04, "Cebu": 0.03,
    "Chiang Mai": 0.03, "Denpasar": 0.03, "Da Nang": 0.04,
}
VENUES_PER_CITY = {"Ho Chi Minh City": 520, "Hanoi": 320}
START, END = datetime(2012, 4, 3), datetime(2014, 1, 31)


def _profile(peaks: list[tuple[float, float]]) -> np.ndarray:
    h = np.arange(24) + 0.5
    p = np.zeros(24)
    for c, s in peaks:
        d = np.minimum(np.abs(h - c), 24 - np.abs(h - c))
        p += np.exp(-0.5 * (d / s) ** 2)
    p += 0.01
    return p / p.sum()


def write_sample(out_dir: Path, users: int = 3000, seed: int = 42) -> None:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    cities = {name: (cc, lat, lon) for name, cc, lat, lon in CITIES if name in USER_SHARE}
    cat_names = [c[0] for c in CATALOG]
    cat_w = np.array([c[3] for c in CATALOG])
    profiles = np.stack([_profile(c[1]) for c in CATALOG])
    hours_rng = np.random.default_rng(seed + 1)  # separate stream: the check-ins stay as they were
    crawl = []

    venues: dict[str, dict[str, np.ndarray]] = {}
    lines = []
    for city, (cc, clat, clon) in cities.items():
        n = VENUES_PER_CITY.get(city, 140)
        wards = [(wl, wn) for c, _, wl, wn in WARDS if c == city]
        if wards:
            centre = np.array(wards)[rng.integers(len(wards), size=n)]
            lat = centre[:, 0] + rng.normal(0, 0.006, n)
            lon = centre[:, 1] + rng.normal(0, 0.006, n)
        else:
            lat = clat + rng.normal(0, 0.05, n)
            lon = clon + rng.normal(0, 0.05, n)
        cat = rng.choice(len(CATALOG), size=n, p=cat_w / cat_w.sum())
        ids = np.array([rng.bytes(12).hex() for _ in range(n)])
        pop = rng.lognormal(0, 1.2, n) * cat_w[cat]
        venues[city] = dict(id=ids, lat=lat, lon=lon, cat=cat, pop=pop)
        for i in range(n):
            lines.append(f"{ids[i]}\t{lat[i]:.6f}\t{lon[i]:.6f}\t{cat_names[cat[i]]}\t{cc}")
            known = SAMPLE_HOURS.get(cat_names[cat[i]])
            if city in SUPPORTED_CITIES and known and hours_rng.random() < HOURS_SHARE:
                jitter = hours_rng.normal(0, 0.0001, 2)  # about 10 m: OSM and Foursquare pins differ
                crawl.append(
                    {"lat": round(lat[i] + jitter[0], 6), "lon": round(lon[i] + jitter[1], 6),
                     "kind": known[0], "opening_hours": known[1]}
                )
    (out_dir / HOURS_FILE).write_text(json.dumps(crawl, ensure_ascii=False), encoding="utf-8")
    # mojibake + junk rows like the raw file
    lines.append(f"{rng.bytes(12).hex()}\t10.776\t106.70\tCafÃ©\tVN")
    lines.append("broken line without fields")
    (out_dir / "raw_POIs.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    names = list(USER_SHARE)
    share = np.array([USER_SHARE[c] for c in names])
    home = rng.choice(len(names), size=users, p=share / share.sum())
    days = (END - START).days
    rows = []
    for u in range(users):
        city = names[home[u]]
        cc = cities[city][0]
        v = venues[city]
        offset = OFFSETS.get(cc, 420)
        for _ in range(rng.poisson(18) + 1):
            day = START + timedelta(days=int(rng.integers(days)))
            first = rng.choice(len(v["id"]), p=v["pop"] / v["pop"].sum())
            hour = rng.choice(24, p=profiles[v["cat"][first]]) + rng.random()
            t = day + timedelta(hours=float(hour))
            cur = first
            for _step in range(int(rng.integers(1, 6))):
                utc = t - timedelta(minutes=offset)
                rows.append(f"{u}\t{v['id'][cur]}\t{utc.strftime('%a %b %d %H:%M:%S +0000 %Y')}\t{offset}")
                dwell = CATALOG[v["cat"][cur]][2] * rng.lognormal(0, 0.35)
                dist = haversine_km(v["lat"][cur], v["lon"][cur], v["lat"], v["lon"])
                hour_next = int(((t.hour * 60 + t.minute + dwell) // 60) % 24)
                w = v["pop"] * np.exp(-dist / 2.0) * profiles[v["cat"], hour_next] * 24
                w[cur] = 0
                nxt = rng.choice(len(w), p=w / w.sum())
                travel = float(dist[nxt]) / 20 * 60 + 3
                t = t + timedelta(minutes=float(dwell + travel))
                cur = nxt
    rows.append("17\tdeadbeef\tnot a date\t420")
    rows.append(f"18\t{venues['Hanoi']['id'][0]}\tMon Feb 30 99:00:00 +0000 2013\t420")
    (out_dir / "raw_Checkins_anonymized.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

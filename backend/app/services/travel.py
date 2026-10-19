"""Travel-time matrix t_ij: OSRM table service, with a straight-line fallback.

No live traffic is used (spec I.1). When OSRM is not configured or not
reachable we estimate door-to-door urban travel from great-circle distance.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

import httpx
import numpy as np

from ml.geo import haversine_km

from ..config import get_settings

log = logging.getLogger(__name__)

DETOUR = 1.35  # road distance / straight-line distance in dense cities
SPEED_KMH = 22.0  # average urban speed (motorbike / car), no traffic data
OVERHEAD_MIN = 4.0  # parking, walking to the entrance

_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()


def estimate_matrix(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    km = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :]) * DETOUR
    m = km / SPEED_KMH * 60.0 + OVERHEAD_MIN
    np.fill_diagonal(m, 0.0)
    return m


def _osrm_matrix(base: str, profile: str, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    coords = ";".join(f"{lo:.6f},{la:.6f}" for la, lo in zip(lat, lon))
    r = httpx.get(f"{base.rstrip('/')}/table/v1/{profile}/{coords}", params={"annotations": "duration"}, timeout=8.0)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "Ok":
        raise RuntimeError(body.get("message", "OSRM error"))
    sec = np.array(body["durations"], dtype=float)
    est = estimate_matrix(lat, lon)
    sec = np.where(np.isfinite(sec), sec / 60.0, est)  # unreachable pairs -> estimate
    m = sec + np.where(np.eye(len(lat), dtype=bool), 0.0, 2.0)  # small stop overhead
    return m


def travel_matrix(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, str]:
    s = get_settings()
    key = (s.osrm_url, tuple(np.round(lat, 5)), tuple(np.round(lon, 5)))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key], "osrm" if s.osrm_url else "estimate"
    source = "estimate"
    if s.osrm_url:
        try:
            m = _osrm_matrix(s.osrm_url, s.osrm_profile, lat, lon)
            source = "osrm"
        except Exception as exc:  # network errors, bad responses
            log.warning("OSRM unavailable, using estimate: %s", exc)
            m = estimate_matrix(lat, lon)
    else:
        m = estimate_matrix(lat, lon)
    if source == "osrm":
        _cache[key] = m
        if len(_cache) > 256:
            _cache.popitem(last=False)
    return m, source

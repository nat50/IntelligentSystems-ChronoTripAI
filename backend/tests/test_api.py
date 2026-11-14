"""API smoke tests against a temporary database trained on the synthetic sample."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="chronotrip-test-"))
os.environ["CHRONOTRIP_DATA_DIR"] = str(_tmp)
os.environ["CHRONOTRIP_DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["CHRONOTRIP_SOLVER_TIME_LIMIT_S"] = "2"

from fastapi.testclient import TestClient  # noqa: E402

from app import orm  # noqa: E402
from app.bootstrap import run as bootstrap  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    bootstrap(sample=True)
    with TestClient(app) as c:
        yield c


def test_cities_and_places(client):
    cities = client.get("/api/cities").json()
    hcm = next(c for c in cities if c["name"] == "Ho Chi Minh City")
    assert hcm["places"] > 100
    places = client.get("/api/places", params={"city": hcm["name"], "limit": 50}).json()
    assert len(places) == 50
    assert all(1 <= p["score"] <= 100 and p["estimated"] for p in places)
    assert places == sorted(places, key=lambda p: -p["score"])
    detail = client.get(f"/api/places/{places[0]['id']}").json()
    assert len(detail["hour_profile"]) == 24


def test_place_attributes_from_the_models(client):
    places = client.get("/api/places", params={"city": "Ho Chi Minh City", "limit": 400}).json()
    levels = {"high", "medium", "low"}
    for p in places:
        assert 10 <= p["duration_lo"] <= p["duration"] <= p["duration_hi"]
        assert {p["conf_m1"], p["conf_m2"], p["conf_m3"], p["confidence"]} <= levels
        assert p["golden_end"] - p["golden_start"] == 120
        assert all(0 <= d <= 6 for d in p["closed_days"])
        # the best time lies inside the opening window (which may run past midnight)
        fits = [p["open_min"] <= p["golden_start"] + shift and p["golden_end"] + shift <= p["close_min"] for shift in (0, 1440)]
        assert any(fits) or p["close_min"] - p["open_min"] < 120, p
    crawled = [p for p in places if p["hours_source"] == "crawl"]
    assert crawled and len(crawled) < len(places)
    assert all(p["confidence"] == "high" for p in crawled)
    museum = next(p for p in crawled if p["label"] == "Museum")
    assert (museum["open_min"], museum["close_min"], museum["closed_days"]) == (480, 1020, [0])
    assert museum["golden_start"] < 12 * 60  # calm morning hours, not the busiest ones
    detail = client.get(f"/api/places/{museum['id']}").json()
    assert len(detail["visit_hist"]) == 13 and sum(detail["visit_hist"]) == detail["n_visits"]
    assert 0 <= detail["one_time_share"] <= 1


def test_version_metrics_for_the_models_screen(client):
    metrics = client.get("/api/admin/overview").json()["versions"][0]["metrics"]
    m3 = metrics["m3"]
    assert m3["mae"] > 0 and m3["rmse"] >= m3["mae"] and 0 <= m3["within_15"] <= 1
    curve = m3["learning_curve"]
    assert len(curve["iteration"]) == len(curve["train"]) == len(curve["valid"]) > 1
    assert m3["largest_errors"] and {"place", "error_min", "n_visits"} <= set(m3["largest_errors"][0])
    for model in ("m1", "m2", "m3"):
        assert set(metrics[model]["by_city"]) == {"Ho Chi Minh City", "Hanoi"}
        assert set(metrics[model]["by_bucket"]) == {"0-9", "10-29", "30+"}
    assert 0 <= metrics["m1"]["ndcg20"] <= 1
    assert metrics["m2"]["hours_eval"]["n"] > 0
    summary = metrics["summary"]
    assert len(summary["visit_bin_edges"]) == 13
    assert summary["data_quality"]["visits"]["kept"] > 0
    assert summary["data_quality"]["opening_hours"]["matched"] > 0
    assert set(summary["confidence"]) == {"m1", "m2", "m3", "window"}


def test_closed_weekday_is_avoided(client):
    places = client.get("/api/places", params={"city": "Ho Chi Minh City", "limit": 400}).json()
    museum = next(p for p in places if p["label"] == "Museum" and p["closed_days"] == [0])
    others = [p["id"] for p in places if not p["closed_days"]][:8]
    body = {
        "city": "Ho Chi Minh City",
        "place_ids": [museum["id"], *others],
        "days": 2,
        "start_date": "2026-11-16",  # a Monday
        "day_start": "08:00",
        "day_end": "21:30",
        "stay": {"lat": 10.8008, "lon": 106.742},
    }
    it = client.post("/api/itinerary/optimize", json=body).json()
    assert museum["id"] not in [s["place"]["id"] for s in it["days"][0]["stops"]]
    one_day = client.post("/api/itinerary/optimize", json=body | {"days": 1}).json()
    assert museum["id"] in [p["id"] for p in one_day["unscheduled"]]
    assert any("closed on every day" in w for w in one_day["warnings"])
    only = client.post("/api/itinerary/optimize", json=body | {"days": 1, "place_ids": [museum["id"]]})
    assert only.status_code == 422
    booked = body | {"days": 1, "locks": [{"place_id": museum["id"], "day": 0}]}
    day = client.post("/api/itinerary/optimize", json=booked).json()["days"][0]
    assert museum["id"] in [s["place"]["id"] for s in day["stops"]]
    assert any("usually closed" in w for w in day["warnings"])


def test_suggest_includes_food(client):
    sug = client.get("/api/places/suggest", params={"city": "Hanoi", "limit": 8}).json()
    assert len(sug) == 8 and any(p["group"] == "food" for p in sug)


def test_optimize_with_lock(client):
    places = client.get("/api/places", params={"city": "Ho Chi Minh City", "limit": 14}).json()
    ids = [p["id"] for p in places]
    body = {
        "city": "Ho Chi Minh City",
        "place_ids": ids,
        "days": 2,
        "day_start": "08:00",
        "day_end": "21:30",
        "stay": {"lat": 10.8008, "lon": 106.742},
        "locks": [{"place_id": ids[3], "day": 1, "start": 14 * 60}],
    }
    r = client.post("/api/itinerary/optimize", json=body)
    assert r.status_code == 200, r.text
    it = r.json()
    assert len(it["days"]) == 2 and it["travel_source"] == "estimate"
    scheduled = [s["place"]["id"] for d in it["days"] for s in d["stops"]]
    assert sorted(scheduled + [p["id"] for p in it["unscheduled"]]) == sorted(ids)
    locked = next(s for s in it["days"][1]["stops"] if s["place"]["id"] == ids[3])
    assert locked["locked"] and locked["start"] >= 14 * 60


def test_optimize_validation(client):
    r = client.post("/api/itinerary/optimize", json={"city": "Hanoi", "place_ids": [], "stay": {"lat": 0, "lon": 0}})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"place_ids": [1], "locks": [{"place_id": 999, "day": 0}]},
        {"place_ids": [1], "locks": [{"place_id": 1, "day": 0}, {"place_id": 1, "day": 0}]},
        {"place_ids": [1], "seed_plan": [[999]]},
        {"place_ids": [1, 2], "seed_plan": [[1, 1]]},
        {"place_ids": [1], "seed_plan": [[], []]},
        {"place_ids": [1], "day_start": "99:99"},
    ],
)
def test_optimize_rejects_inconsistent_input(client, payload):
    body = {
        "city": "Hanoi",
        "place_ids": [1],
        "days": 1,
        "day_start": "08:00",
        "day_end": "21:30",
        "stay": {"lat": 0, "lon": 0},
    }
    body.update(payload)
    r = client.post("/api/itinerary/optimize", json=body)
    assert r.status_code == 422, r.text


def test_place_detail_hides_inactive_versions(client):
    place_id = client.get("/api/places", params={"city": "Hanoi", "limit": 1}).json()[0]["id"]
    with SessionLocal() as s:
        place = s.get(orm.Place, place_id)
        assert place is not None
        active_version = place.version
        place.version = "inactive-test-version"
        s.commit()
    try:
        assert client.get(f"/api/places/{place_id}").status_code == 404
    finally:
        with SessionLocal() as s:
            place = s.get(orm.Place, place_id)
            assert place is not None
            place.version = active_version
            s.commit()


def test_root_bootstrap_entrypoint_is_available():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "app.bootstrap", "--help"],
        cwd=root,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "First-run setup" in result.stdout


def test_admin_train_and_activate(client):
    ov = client.get("/api/admin/overview").json()
    assert ov["versions"][0]["is_active"] and not ov["dataset_found"]
    assert {s["country"] for s in ov["country_stats"]} >= {"VN", "ID"}
    job = client.post("/api/admin/train", json={"source": "sample"}).json()
    for _ in range(240):
        job = client.get(f"/api/admin/jobs/{job['id']}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert job["status"] == "done", job
    assert set(job["models"].values()) == {"trained"}
    act = client.post(f"/api/admin/versions/{job['version']}/activate").json()
    assert act["is_active"] and act["version"] == "v2"

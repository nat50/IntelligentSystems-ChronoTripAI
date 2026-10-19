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

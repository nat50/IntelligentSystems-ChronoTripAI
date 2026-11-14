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
        assert set(metrics[model]["by_city"]) == {"Ho Chi Minh City", "Hanoi", "Da Nang"}
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


# --------------------------------------------------------------------------- #
# Figma screens beyond the models: T1-T4 and the data console D1-D4
# --------------------------------------------------------------------------- #
HCM_STAY = {"lat": 10.8008, "lon": 106.742}


def wait_for(get, done, tries=240):
    out = None
    for _ in range(tries):
        out = get()
        if done(out):
            return out
        time.sleep(0.5)
    raise AssertionError(f"timed out: {out}")


def test_da_nang_interests_and_search(client):
    cities = {c["name"]: c for c in client.get("/api/cities").json()}
    assert cities["Da Nang"]["places"] > 20
    culture = client.get("/api/places", params={"city": "Hanoi", "interest": "culture", "limit": 200}).json()
    assert culture and all(p["interest"] == "culture" for p in culture)
    two = client.get("/api/places", params=[("city", "Hanoi"), ("interest", "food"), ("interest", "nature")]).json()
    assert {p["interest"] for p in two} == {"food", "nature"}
    found = client.get("/api/places", params={"city": "Ho Chi Minh City", "q": "museum"}).json()
    assert found and all("museum" in (p["label"] + p["category"]).lower() for p in found)
    one = found[0]
    by_name = client.get("/api/places", params={"city": "Ho Chi Minh City", "q": f"{one['label']} · {one['ward']}"}).json()
    assert one["id"] in [p["id"] for p in by_name]
    by_id = client.get("/api/places", params={"city": "Ho Chi Minh City", "q": one["venue"][:8]}).json()
    assert one["id"] in [p["id"] for p in by_id]
    sug = client.get("/api/places/suggest", params={"city": "Da Nang", "interest": "culture"}).json()
    assert sug and {p["interest"] for p in sug} <= {"culture", "food"}
    detail = client.get(f"/api/places/{one['id']}").json()
    assert set(detail["model_versions"]) == {"m1", "m2", "m3"} and detail["quality"] in ("good", "low_data", "missing_hours")


def test_must_visit_and_no_plan_fits(client):
    places = client.get("/api/places", params={"city": "Ho Chi Minh City", "limit": 400}).json()
    # places open all morning and afternoon, about an hour each: three of them do not fit in 09:00-11:00
    usable = [p for p in places if not p["closed_days"] and p["open_min"] <= 9 * 60 and p["close_min"] >= 18 * 60
              and 45 <= p["duration"] <= 90]
    ids = [p["id"] for p in usable[:3]]
    body = {
        "city": "Ho Chi Minh City", "place_ids": ids, "days": 1, "day_start": "09:00", "day_end": "11:00",
        "stay": HCM_STAY, "must_visit": ids,
    }
    it = client.post("/api/itinerary/optimize", json=body).json()
    fit = it["plan_fit"]
    assert fit and set(fit["missing"]) <= set(ids) and fit["needed_min"] > fit["available_min"]
    kinds = {f["kind"] for f in fit["fixes"]}
    assert {"add_day", "extend_day"} <= kinds
    assert sum(f["recommended"] for f in fit["fixes"]) == (1 if any(f["fits"] for f in fit["fixes"]) else 0)
    # a fix is a patch of the request: applying a fitting one schedules every must-visit place
    fix = next(f for f in fit["fixes"] if f["recommended"])
    fixed = client.post("/api/itinerary/optimize", json=body | fix["patch"]).json()
    assert fixed["plan_fit"] is None
    assert set(ids) <= {s["place"]["id"] for d in fixed["days"] for s in d["stops"]}
    bad = client.post("/api/itinerary/optimize", json=body | {"must_visit": [999999]})
    assert bad.status_code == 422


def test_optimize_job_reports_progress(client):
    ids = [p["id"] for p in client.get("/api/places", params={"city": "Hanoi", "limit": 12}).json()]
    body = {"city": "Hanoi", "place_ids": ids, "days": 2, "day_start": "08:00", "day_end": "21:30",
            "stay": {"lat": 21.031, "lon": 105.85}}
    job = client.post("/api/itinerary/jobs", json=body)
    assert job.status_code == 202
    job_id = job.json()["id"]
    done = wait_for(lambda: client.get(f"/api/itinerary/jobs/{job_id}").json(), lambda j: j["status"] != "running")
    assert done["status"] == "done" and all(st["done"] for st in done["steps"])
    assert done["generation"] > 0 and done["best_stops"] > 0 and done["result"]["days"]
    other = client.post("/api/itinerary/jobs", json=body).json()["id"]
    assert client.delete(f"/api/itinerary/jobs/{other}").status_code == 200
    end = wait_for(lambda: client.get(f"/api/itinerary/jobs/{other}").json(), lambda j: j["status"] != "running")
    assert end["status"] in ("cancelled", "done")
    assert client.get("/api/itinerary/jobs/nope").status_code == 404


def test_saved_trip_share_export_and_edits(client):
    places = client.get("/api/places", params={"city": "Ho Chi Minh City", "limit": 8}).json()
    req = {"city": "Ho Chi Minh City", "place_ids": [p["id"] for p in places], "days": 2, "start_date": "2026-11-14",
           "day_start": "08:00", "day_end": "21:30", "stay": HCM_STAY | {"label": "Thao Dien Hotel"}}
    it = client.post("/api/itinerary/optimize", json=req).json()
    created = client.post("/api/trips", json={"request": req, "itinerary": it})
    assert created.status_code == 201
    trip = created.json()
    tid, token = trip["id"], trip["edit_token"]
    auth = {"X-Trip-Token": token}
    assert trip["title"] == "Ho Chi Minh City · 2 days" and trip["end_date"] == "2026-11-15"
    assert trip["stops"] == sum(len(d["stops"]) for d in it["days"]) and len(trip["overview"]) == 2
    assert trip["overview"][0]["date"] == "2026-11-14" and trip["stale_places"] == []
    assert client.get(f"/api/trips/{tid}").status_code == 404
    assert client.get(f"/api/trips/{tid}", headers={"X-Trip-Token": "wrong"}).status_code == 404
    assert client.get(f"/api/trips/{tid}", headers=auth).json()["status"] in ("upcoming", "past")
    draft = client.post("/api/trips", json={"request": req | {"start_date": None}}).json()
    listed = client.post("/api/trips/lookup", json={"trips": [
        {"id": draft["id"], "token": draft["edit_token"]}, {"id": tid, "token": token}, {"id": tid + 999, "token": "x"},
    ]}).json()
    assert [t["id"] for t in listed] == [tid, draft["id"]] and listed[1]["status"] == "draft"
    assert client.patch(f"/api/trips/{tid}", headers=auth, json={"title": "HCMC weekend"}).json()["title"] == "HCMC weekend"

    shared = client.put(f"/api/trips/{tid}/share", headers=auth, json={"enabled": True}).json()
    slug = shared["share_slug"]
    assert slug.startswith("hcm-2d-")
    public = client.get(f"/api/shared/{slug}").json()
    assert public["title"] == "HCMC weekend" and "edit_token" not in public
    gpx = client.get(f"/api/shared/{slug}/export.gpx")
    assert gpx.status_code == 200 and gpx.headers["content-type"].startswith("application/gpx+xml")
    assert gpx.text.count("<wpt ") == trip["stops"] and "<time>2026-11-14T" in gpx.text and "<rte>" in gpx.text
    assert client.get(f"/api/trips/{tid}/export.gpx", params={"token": token}).status_code == 200
    ics = client.get(f"/api/trips/{tid}/export.ics", headers=auth)
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    body = ics.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert body.count("BEGIN:VEVENT") == trip["stops"] and "TZID:Asia/Ho_Chi_Minh" in body
    first = it["days"][0]["stops"][0]
    hhmm = f"{first['start'] // 60:02d}{first['start'] % 60:02d}"
    assert f"DTSTART;TZID=Asia/Ho_Chi_Minh:20261114T{hhmm}00" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    assert client.get(f"/api/shared/{slug}/export.ics").status_code == 200
    undated = client.post("/api/trips", json={"request": req | {"start_date": None}, "itinerary": it}).json()
    assert client.get(f"/api/trips/{undated['id']}/export.ics", headers={"X-Trip-Token": undated["edit_token"]}).status_code == 409
    client.put(f"/api/trips/{tid}/share", headers=auth, json={"enabled": False})
    assert client.get(f"/api/shared/{slug}").status_code == 404
    assert client.put(f"/api/trips/{tid}/share", headers=auth, json={"enabled": True}).json()["share_slug"] == slug

    stop = it["days"][0]["stops"][0]
    events = {"events": [{"kind": "set_duration", "place_id": stop["place"]["id"], "day": 0, "value": 30}]}
    assert client.post(f"/api/trips/{tid}/edits", headers=auth, json=events).json()["stored"] == 0
    client.patch(f"/api/trips/{tid}", headers=auth, json={"improve_estimates": True})
    assert client.post(f"/api/trips/{tid}/edits", headers=auth, json=events).json()["stored"] == 1
    with SessionLocal() as s:
        log = s.query(orm.EditLog).order_by(orm.EditLog.id.desc()).first()
        assert log.venue == stop["place"]["venue"] and log.predicted_duration == stop["place"]["duration"]

    assert client.delete(f"/api/trips/{tid}", headers=auth).status_code == 204
    assert client.get(f"/api/trips/{tid}", headers=auth).status_code == 404


def test_data_console_and_place_explorer(client):
    d = client.get("/api/admin/data").json()
    assert {s["key"] for s in d["sources"]} == {"checkins", "opening_hours", "travel", "edit_logs"}
    assert {c["name"] for c in d["cities"]} == {"Ho Chi Minh City", "Hanoi", "Da Nang"} and d["places"] > 0
    order = {"high": 0, "medium": 1, "low": 2}
    assert [order[i["impact"]] for i in d["issues"]] == sorted(order[i["impact"]] for i in d["issues"])
    assert len(d["pipeline"]) == 5
    for quality in ("good", "low_data", "missing_hours"):
        part = client.get("/api/admin/places", params={"city": "Hanoi", "quality": quality, "limit": 500}).json()
        assert part["total"] > 0 and all(p["quality"] == quality for p in part["places"])
    found = client.get("/api/admin/places", params={"city": "Hanoi", "q": "temple"}).json()["places"]
    assert found and all(p["name"].startswith("Temple") for p in found)
    assert client.get("/api/admin/hours").json()["running"] is False


def test_models_screen_train_compare_activate_rollback(client):
    cards = client.get("/api/admin/models").json()
    assert [c["key"] for c in cards] == ["m1", "m2", "m3"]
    m3 = next(c for c in cards if c["key"] == "m3")
    origin = m3["active_version"]
    assert m3["split"]["kind"] == "time" and set(m3["split"]["shares"]) == {"train", "val", "test"}
    assert client.post("/api/admin/models/m3/train", json={"settings": {"depth": 3}}).status_code == 422
    job = client.post("/api/admin/models/m3/train", json={"settings": {"num_leaves": 15}}).json()
    job = wait_for(lambda: client.get(f"/api/admin/jobs/{job['id']}").json(), lambda j: j["status"] in ("done", "failed"))
    assert job["status"] == "done", job
    new = job["version"]
    detail = client.get("/api/admin/models/m3").json()
    assert detail["status"] == "new_run_ready" and detail["latest"] == new
    row = next(v for v in detail["versions"] if v["version"] == new)
    assert row["settings"]["num_leaves"] == 15 and row["headline"]["name"] == "MAE" and not row["active"]
    m1_versions = [v["version"] for v in client.get("/api/admin/models/m1").json()["versions"]]
    assert new not in m1_versions  # this run trained only M3
    impact = client.get(f"/api/admin/models/m3/versions/{new}/impact").json()
    assert impact["places_compared"] > 0 and impact["unit"] == "min" and "saved trip" in impact["message"]

    act = client.post(f"/api/admin/models/m3/versions/{new}/activate").json()
    act = wait_for(lambda: client.get(f"/api/admin/jobs/{act['id']}").json(), lambda j: j["status"] in ("done", "failed"))
    assert act["status"] == "done", act
    after = client.get("/api/admin/models/m3").json()
    assert after["active_version"] == new and after["status"] == "active"
    m1_before = next(c for c in cards if c["key"] == "m1")["active_version"]
    assert client.get("/api/admin/models/m1").json()["active_version"] == m1_before
    assert client.post(f"/api/admin/models/m3/versions/{new}/activate").status_code == 409  # already active
    # roll back: the original combination already exists as a version, so it is just activated
    back = client.post(f"/api/admin/models/m3/versions/{origin}/activate").json()
    assert back["status"] == "done"
    assert client.get("/api/admin/models/m3").json()["active_version"] == origin


def test_optimizer_settings_benchmark_and_apply(client, monkeypatch):
    from app.services import optimizer

    monkeypatch.setattr(optimizer, "CASES", optimizer.CASES[1:3])
    monkeypatch.setattr(optimizer, "RUNS", 1)
    state = client.get("/api/admin/optimizer").json()
    assert state["active"]["objective"] == {"popularity": 0.6, "golden": 0.3, "travel": 0.1}
    bad = {"objective": {"popularity": 0.9, "golden": 0.3, "travel": 0.1}}
    assert client.post("/api/admin/optimizer/benchmark", json=bad).status_code == 422
    new = {"population": 40, "generations": 60, "crossover": 0.8, "mutation": 0.1, "time_limit_s": 1,
           "local_search": True, "objective": {"popularity": 0.5, "golden": 0.4, "travel": 0.1}}
    bench = client.post("/api/admin/optimizer/benchmark", json=new)
    assert bench.status_code == 202
    bench_id = bench.json()["id"]
    bench = wait_for(lambda: client.get(f"/api/admin/optimizer/benchmarks/{bench_id}").json(),
                     lambda b: b["status"] != "running")
    assert bench["status"] == "done", bench
    assert len(bench["cases"]) == 2 and bench["median_runtime_s"] > 0 and bench["score_change"] is not None
    assert len(bench["curve"]["generation"]) == len(bench["curve"]["active"]) == len(bench["curve"]["new"])
    applied = client.post("/api/admin/optimizer/apply", json=new).json()
    assert applied["active"]["population"] == 40 and applied["last_benchmark"]["id"] == bench_id
    ids = [p["id"] for p in client.get("/api/places", params={"city": "Hanoi", "limit": 6}).json()]
    it = client.post("/api/itinerary/optimize", json={
        "city": "Hanoi", "place_ids": ids, "days": 1, "day_start": "08:00", "day_end": "21:30",
        "stay": {"lat": 21.031, "lon": 105.85}}).json()
    assert it["generations"] <= 60 and it["weights"]["golden_bonus"] == pytest.approx(0.25 * 0.4 / 0.3)
    client.post("/api/admin/optimizer/apply", json={})  # back to the defaults for any later test

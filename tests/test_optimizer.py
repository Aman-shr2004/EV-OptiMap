import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimizer.distance import haversine_matrix, nearest_distance  # noqa: E402
from optimizer.evaluation import run_optimization  # noqa: E402
from optimizer.greedy import greedy_max_coverage, random_baseline  # noqa: E402


def test_haversine_known_distance():
    # Indore (Rajwada) to Bhopal is ~ 170-190 km straight line
    d = haversine_matrix([[22.7196, 75.8577]], [[23.2599, 77.4126]])[0, 0]
    assert 150 < d < 200
    assert haversine_matrix([[1, 1]], [[1, 1]])[0, 0] == pytest.approx(0)


def test_nearest_distance_no_stations():
    assert np.isinf(nearest_distance(np.array([[22.7, 75.8]]), np.zeros((0, 2)))).all()


def test_greedy_small_synthetic():
    # 4 demand points; cand0 covers {0,1}, cand1 covers {1,2,3}, cand2 covers {3}
    w = np.array([1.0, 1.0, 1.0, 1.0])
    cover = np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 1, 1]], dtype=bool)
    sel, gains = greedy_max_coverage(w, cover, np.zeros(4, dtype=bool), 2)
    assert sel == [1, 0]
    assert gains == [3.0, 1.0]


def test_greedy_ignores_already_covered():
    w = np.array([5.0, 1.0])
    cover = np.array([[1, 0], [0, 1]], dtype=bool)
    sel, _ = greedy_max_coverage(w, cover, np.array([True, False]), 1)
    assert sel == [1]  # demand 0 already covered by existing charger


def test_greedy_stops_when_no_gain():
    w = np.array([1.0])
    cover = np.array([[1, 1]], dtype=bool)
    sel, _ = greedy_max_coverage(w, cover, np.zeros(1, dtype=bool), 5)
    assert len(sel) == 1


def test_random_baseline_not_better_than_best_possible():
    rng = np.random.default_rng(1)
    cover = rng.random((50, 20)) < 0.1
    w = rng.random(50)
    already = np.zeros(50, dtype=bool)
    sel, _ = greedy_max_coverage(w, cover, already, 4)
    greedy_val = w[cover[:, sel].any(axis=1)].sum()
    rb = random_baseline(w, cover, already, 4, trials=100)
    assert greedy_val >= rb["mean"]


def _data():
    demand = np.array([[22.70, 75.80], [22.70, 75.801], [22.80, 75.90]])
    return {"demand": demand, "demand_props": [{"weight": 1.0}] * 3,
            "candidates": np.array([[22.70, 75.80], [22.80, 75.90], [22.75, 75.85]]),
            "chargers": np.zeros((0, 2))}


def test_run_optimization_end_to_end():
    r = run_optimization(_data(), k=2, radius_km=1.0, random_trials=20)
    assert r["greedy"]["weighted_coverage_pct"] == pytest.approx(100.0)
    assert r["greedy"]["stations"] == 2
    assert len(r["selected"]) == 2


def test_budget_limits_stations():
    r = run_optimization(_data(), k=5, radius_km=1.0, cost_per_station=100, budget=250, random_trials=5)
    assert r["greedy"]["stations"] <= 2


def test_invalid_inputs():
    with pytest.raises(ValueError):
        run_optimization(_data(), k=2, radius_km=0)
    with pytest.raises(ValueError):
        run_optimization({**_data(), "demand": np.zeros((0, 2))}, k=2)


def test_flask_api(tmp_path, monkeypatch):
    import app as appmod
    from database import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    client = appmod.app.test_client()
    ds = client.get("/api/dataset").get_json()
    assert ds["counts"]["demand"] > 0
    r = client.post("/api/optimize", json={"k": 5, "radius_km": 2})
    assert r.status_code == 200
    body = r.get_json()
    assert body["greedy"]["weighted_coverage_pct"] >= body["existing_coverage"]["weighted_coverage_pct"]
    assert client.get(f"/export/{body['run_id']}.csv").status_code == 200
    assert client.get(f"/results/{body['run_id']}").status_code == 200
    assert client.post("/api/optimize", json={"k": "abc"}).status_code == 400


def test_live_editing_api(tmp_path, monkeypatch):
    import shutil
    import app as appmod
    from database import db
    from optimizer import demand as dm

    proc = tmp_path / "processed"
    shutil.copytree(dm.PROCESSED, proc, ignore=shutil.ignore_patterns("*.orig"))
    monkeypatch.setattr(appmod, "PROCESSED", str(proc))
    monkeypatch.setattr(dm, "PROCESSED", str(proc))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    appmod._DATA.clear()
    monkeypatch.setattr(appmod, "load_dataset", lambda: dm.load_dataset(str(proc)))

    c = appmod.app.test_client()
    n0 = c.get("/api/dataset").get_json()["counts"]
    assert c.post("/api/charger", json={"lat": 22.72, "lon": 75.86}).status_code == 200
    assert c.get("/api/dataset").get_json()["counts"]["chargers"] == n0["chargers"] + 1
    assert c.delete("/api/charger/0").status_code == 200
    assert c.delete("/api/charger/9999").status_code == 404
    r = c.post("/api/demand", json={"lat": 22.72, "lon": 75.86, "category": "commercial", "count": 25})
    assert r.get_json()["added"] == 25
    assert c.post("/api/demand", json={"lat": 22.7, "lon": 75.8, "category": "bogus"}).status_code == 400
    assert c.post("/api/charger", json={"lat": 999, "lon": 75}).status_code == 400
    # live (unsaved) optimization has no run_id
    body = c.post("/api/optimize", json={"k": 3, "save": False}).get_json()
    assert "run_id" not in body
    assert c.post("/api/reset").status_code == 200
    assert c.get("/api/dataset").get_json()["counts"]["chargers"] == n0["chargers"]
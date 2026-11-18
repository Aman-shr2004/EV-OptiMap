"""EV-OptiMap Flask application.

Run:  python app.py   then open http://127.0.0.1:5000
"""
import csv
import io
import json
import os
import shutil
import time

import numpy as np
from flask import Flask, Response, jsonify, render_template, request

from data_collection import download_osm
from database import db
from optimizer.demand import DEFAULT_CATEGORY_WEIGHTS, PROCESSED, load_dataset
from optimizer.evaluation import compare_budgets, run_optimization

app = Flask(__name__)
_DATA = {}
_EDITABLE = ("existing_chargers.geojson", "demand_points.geojson")


def _backup_originals():
    """Keep a pristine copy so live edits can be reset."""
    for name in _EDITABLE:
        p = os.path.join(PROCESSED, name)
        if os.path.exists(p) and not os.path.exists(p + ".orig"):
            shutil.copyfile(p, p + ".orig")


def _save_geojson(name, coords, props):
    feats = [{"type": "Feature",
              "geometry": {"type": "Point", "coordinates": [round(float(lon), 6), round(float(lat), 6)]},
              "properties": p} for (lat, lon), p in zip(coords, props)]
    with open(os.path.join(PROCESSED, name), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)


def get_data():
    if "d" not in _DATA:
        if not os.path.exists(os.path.join(PROCESSED, "demand_points.geojson")):
            download_osm.main([])  # generate synthetic demo data
        _backup_originals()
        _DATA["d"] = load_dataset()
        _DATA["version"] = time.time()
    return _DATA["d"]


def _touch():
    _DATA["version"] = time.time()


def _latlon(p):
    lat = _num(p, "lat", None, float, -90, 90)
    lon = _num(p, "lon", None, float, -180, 180)
    if lat is None or lon is None:
        raise ValueError("lat and lon are required")
    return lat, lon


def _num(payload, key, default, cast=float, lo=None, hi=None):
    v = payload.get(key, default)
    if v in (None, ""):
        return default
    try:
        v = cast(v)
    except (TypeError, ValueError):
        raise ValueError(f"'{key}' must be a number")
    if lo is not None and v < lo:
        raise ValueError(f"'{key}' must be >= {lo}")
    if hi is not None and v > hi:
        raise ValueError(f"'{key}' must be <= {hi}")
    return v


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/results/<int:run_id>")
def results_page(run_id):
    r = db.get_run(run_id)
    if r is None:
        return "Run not found", 404
    return render_template("results.html", run_id=run_id, r=r)


@app.route("/api/charger", methods=["POST"])
def api_add_charger():
    d = get_data()
    try:
        lat, lon = _latlon(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    d["chargers"] = np.vstack([d["chargers"], [[lat, lon]]])
    d["charger_props"].append({"id": len(d["charger_props"]), "name": "User-added charger", "source": "user"})
    _save_geojson("existing_chargers.geojson", d["chargers"], d["charger_props"])
    _touch()
    return jsonify({"ok": True, "count": len(d["chargers"])})


@app.route("/api/charger/<int:idx>", methods=["DELETE"])
def api_delete_charger(idx):
    d = get_data()
    if idx < 0 or idx >= len(d["chargers"]):
        return jsonify({"error": "charger not found"}), 404
    d["chargers"] = np.delete(d["chargers"], idx, axis=0)
    del d["charger_props"][idx]
    _save_geojson("existing_chargers.geojson", d["chargers"], d["charger_props"])
    _touch()
    return jsonify({"ok": True, "count": len(d["chargers"])})


@app.route("/api/demand", methods=["POST"])
def api_add_demand():
    """Add a demand hotspot: `count` weighted points scattered around (lat, lon)."""
    d = get_data()
    p = request.get_json(silent=True) or {}
    try:
        lat, lon = _latlon(p)
        count = _num(p, "count", 30, int, 1, 500)
        spread_km = _num(p, "spread_km", 0.3, float, 0.01, 5)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    cat = p.get("category", "commercial")
    if cat not in DEFAULT_CATEGORY_WEIGHTS:
        return jsonify({"error": f"category must be one of {list(DEFAULT_CATEGORY_WEIGHTS)}"}), 400
    rng = np.random.default_rng()
    dlat = spread_km / 111.0
    dlon = spread_km / (111.0 * max(np.cos(np.radians(lat)), 0.01))
    pts = np.column_stack([rng.normal(lat, dlat, count), rng.normal(lon, dlon, count)])
    start = len(d["demand_props"])
    for i in range(count):
        w = DEFAULT_CATEGORY_WEIGHTS[cat] * float(rng.uniform(0.7, 1.3))
        d["demand_props"].append({"id": start + i, "category": cat, "weight": round(w, 3), "source": "user"})
    d["demand"] = np.vstack([d["demand"], pts])
    _save_geojson("demand_points.geojson", d["demand"], d["demand_props"])
    _touch()
    return jsonify({"ok": True, "added": count, "count": len(d["demand"])})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    for name in _EDITABLE:
        p = os.path.join(PROCESSED, name)
        if os.path.exists(p + ".orig"):
            shutil.copyfile(p + ".orig", p)
    _DATA.pop("d", None)
    get_data()
    return jsonify({"ok": True})


@app.route("/api/version")
def api_version():
    get_data()
    return jsonify({"version": _DATA["version"]})


@app.route("/api/dataset")
def api_dataset():
    d = get_data()
    return jsonify({
        "version": _DATA["version"],
        "chargers": d["chargers"].tolist(),
        "candidates": d["candidates"].tolist(),
        "demand": [[lat, lon, p.get("weight", 1.0)] for (lat, lon), p in zip(d["demand"], d["demand_props"])],
        "source": (d["demand_props"][0].get("source") if d["demand_props"] else None),
        "counts": {"chargers": len(d["chargers"]), "candidates": len(d["candidates"]),
                   "demand": len(d["demand"])},
    })


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    p = request.get_json(silent=True) or {}
    try:
        k = _num(p, "k", 10, int, 0, 200)
        radius = _num(p, "radius_km", 2.0, float, 0.1, 20)
        cost = _num(p, "cost_per_station", None, float, 0)
        budget = _num(p, "budget", None, float, 0)
        result = run_optimization(get_data(), k=k, radius_km=radius,
                                  cost_per_station=cost, budget=budget)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    # live (auto) runs pass save=false so history isn't flooded
    if p.get("save", True):
        result["run_id"] = db.save_run(result)
    return jsonify(result)


@app.route("/api/compare")
def api_compare():
    try:
        radius = _num(request.args, "radius_km", 2.0, float, 0.1, 20)
        return jsonify(compare_budgets(get_data(), radius_km=radius))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/history")
def api_history():
    return jsonify(db.list_runs())


@app.route("/api/run/<int:run_id>")
def api_run(run_id):
    r = db.get_run(run_id)
    return (jsonify(r), 200) if r else (jsonify({"error": "not found"}), 404)


@app.route("/export/<int:run_id>.csv")
def export_csv(run_id):
    r = db.get_run(run_id)
    if r is None:
        return "Run not found", 404
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "candidate_id", "lat", "lon", "new_demand_covered", "cost"])
    for s in r["selected"]:
        w.writerow([s["rank"], s["candidate_id"], s["lat"], s["lon"],
                    round(s["new_demand_covered"], 3), s["cost"] if s["cost"] is not None else ""])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=ev_optimap_run_{run_id}.csv"})


if __name__ == "__main__":
    app.run(debug=True)
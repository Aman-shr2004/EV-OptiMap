"""Load GeoJSON point datasets and build demand arrays."""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(ROOT, "data", "processed")

DEFAULT_CATEGORY_WEIGHTS = {"residential": 1.0, "commercial": 3.0, "parking": 2.5, "public": 2.0}


def load_points(path):
    """Return (coords Nx2 array of [lat, lon], list of properties)."""
    if not os.path.exists(path):
        return np.zeros((0, 2)), []
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    coords, props = [], []
    for ft in gj.get("features", []):
        g = ft.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][:2]
        coords.append([lat, lon])
        props.append(ft.get("properties", {}) or {})
    return np.array(coords, dtype=float).reshape(-1, 2), props


def load_dataset(folder=PROCESSED):
    chargers, cprops = load_points(os.path.join(folder, "existing_chargers.geojson"))
    cands, kprops = load_points(os.path.join(folder, "candidate_sites.geojson"))
    demand, dprops = load_points(os.path.join(folder, "demand_points.geojson"))
    return {"chargers": chargers, "charger_props": cprops,
            "candidates": cands, "candidate_props": kprops,
            "demand": demand, "demand_props": dprops}


def demand_weights(props, category_weights=None):
    """Weight per demand point. Uses stored 'weight' unless category_weights override is given."""
    out = []
    for p in props:
        if category_weights and p.get("category") in category_weights:
            out.append(float(category_weights[p["category"]]))
        else:
            out.append(float(p.get("weight", 1.0)))
    return np.array(out, dtype=float)
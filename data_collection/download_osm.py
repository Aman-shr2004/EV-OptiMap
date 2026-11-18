"""Data collection for EV-OptiMap.

Two modes:
  python data_collection/download_osm.py            -> synthetic Indore-like data (works offline)
  python data_collection/download_osm.py --osm      -> real OpenStreetMap data via OSMnx

Outputs (data/processed/):
  existing_chargers.geojson, candidate_sites.geojson, demand_points.geojson, data_summary.csv

NOTE: synthetic data is for demo/testing only. Do not present it as real Indore data.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(ROOT, "data", "processed")
RAW = os.path.join(ROOT, "data", "raw")

PLACE = "Indore, Madhya Pradesh, India"
# Approximate bounding box of Indore city (south, west, north, east)
BBOX = (22.64, 75.77, 22.82, 75.96)

# Demand category -> default weight (project assumption, configurable)
CATEGORY_WEIGHTS = {
    "residential": 1.0,
    "commercial": 3.0,
    "parking": 2.5,
    "public": 2.0,
}

# Approximate hotspot locations (name, lat, lon, spread, relative size)
HOTSPOTS = [
    ("Rajwada", 22.7196, 75.8577, 0.010, 1.0),
    ("Vijay Nagar", 22.7533, 75.8937, 0.012, 1.3),
    ("Palasia", 22.7244, 75.8839, 0.008, 1.0),
    ("Bhawarkuan", 22.6934, 75.8670, 0.009, 0.8),
    ("Rau", 22.6400, 75.8100, 0.010, 0.5),
    ("Scheme 78", 22.7480, 75.9040, 0.009, 0.8),
    ("Airport Road", 22.7220, 75.8010, 0.008, 0.5),
    ("Sudama Nagar", 22.6950, 75.8200, 0.009, 0.7),
    ("MR-10", 22.7600, 75.8800, 0.010, 0.7),
    ("Khajrana", 22.7360, 75.9000, 0.008, 0.6),
]


def _feature(lon, lat, **props):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(float(lon), 6), round(float(lat), 6)]},
            "properties": props}


def _write_geojson(path, features):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)


def generate_synthetic(seed=42, n_demand=1500, n_chargers=8, grid_step=0.008):
    rng = np.random.default_rng(seed)
    south, west, north, east = BBOX

    # Demand points around hotspots, mixed categories
    sizes = np.array([h[4] for h in HOTSPOTS])
    probs = sizes / sizes.sum()
    cats = list(CATEGORY_WEIGHTS)
    cat_p = [0.5, 0.25, 0.1, 0.15]
    demand = []
    for i in range(n_demand):
        h = HOTSPOTS[rng.choice(len(HOTSPOTS), p=probs)]
        lat = np.clip(rng.normal(h[1], h[3]), south, north)
        lon = np.clip(rng.normal(h[2], h[3]), west, east)
        cat = cats[rng.choice(len(cats), p=cat_p)]
        w = CATEGORY_WEIGHTS[cat] * float(rng.uniform(0.7, 1.3))
        demand.append(_feature(lon, lat, id=i, category=cat, weight=round(w, 3), source="synthetic"))

    # Existing chargers: a few at big hotspots
    chargers = []
    idx = rng.choice(len(HOTSPOTS), size=n_chargers, replace=False)
    for k, hi in enumerate(idx):
        h = HOTSPOTS[hi]
        chargers.append(_feature(h[2] + rng.normal(0, 0.003), h[1] + rng.normal(0, 0.003),
                                 id=k, name=f"Synthetic charger near {h[0]}", source="synthetic"))

    # Candidate sites: regular grid
    cands = []
    cid = 0
    for lat in np.arange(south, north, grid_step):
        for lon in np.arange(west, east, grid_step):
            cands.append(_feature(lon, lat, id=cid, source="synthetic_grid", cost=None))
            cid += 1
    return chargers, cands, demand


def download_osm():
    """Real OSM download. Requires osmnx + geopandas and internet access."""
    import osmnx as ox
    import geopandas as gpd  # noqa: F401

    os.makedirs(RAW, exist_ok=True)

    def pts(gdf):
        g = gdf.copy()
        g["geometry"] = g.geometry.representative_point()
        return g

    print("Downloading charging stations...")
    try:
        ch = ox.features_from_place(PLACE, {"amenity": "charging_station"})
        ch = pts(ch)
    except Exception as e:  # no features found
        print("  no charging stations found:", e)
        ch = None
    chargers = []
    if ch is not None:
        for k, (_, r) in enumerate(ch.iterrows()):
            chargers.append(_feature(r.geometry.x, r.geometry.y, id=k,
                                     name=str(r.get("name", "") or ""), source="osm"))
    # de-duplicate (within ~30 m)
    chargers = _dedupe(chargers, 0.0003)

    print("Downloading demand proxy POIs...")
    tag_sets = [
        ("residential", {"landuse": "residential"}),
        ("commercial", {"shop": True}),
        ("commercial", {"amenity": ["marketplace", "restaurant", "cinema", "bank"]}),
        ("commercial", {"landuse": "commercial"}),
        ("parking", {"amenity": "parking"}),
        ("public", {"amenity": ["hospital", "university", "college", "bus_station"]}),
        ("public", {"railway": "station"}),
        ("public", {"aeroway": "terminal"}),
    ]
    demand = []
    did = 0
    for cat, tags in tag_sets:
        try:
            g = pts(ox.features_from_place(PLACE, tags))
        except Exception as e:
            print(f"  {tags}: none ({e})")
            continue
        for _, r in g.iterrows():
            demand.append(_feature(r.geometry.x, r.geometry.y, id=did, category=cat,
                                   weight=CATEGORY_WEIGHTS[cat], source="osm"))
            did += 1
    print(f"  {len(demand)} demand points")

    print("Downloading road network (for candidate sites)...")
    G = ox.graph_from_place(PLACE, network_type="drive")
    ox.save_graphml(G, os.path.join(PROCESSED, "indore_roads.graphml"))
    nodes = ox.graph_to_gdfs(G, edges=False)
    cands = []
    seen = set()
    cid = 0
    for _, r in nodes.iterrows():  # thin intersections onto a ~500 m grid
        key = (round(r.geometry.y / 0.005), round(r.geometry.x / 0.005))
        if key in seen:
            continue
        seen.add(key)
        cands.append(_feature(r.geometry.x, r.geometry.y, id=cid, source="osm_intersection", cost=None))
        cid += 1
    return chargers, cands, demand


def _dedupe(features, tol):
    kept = []
    for f in features:
        x, y = f["geometry"]["coordinates"]
        if all(abs(x - k["geometry"]["coordinates"][0]) > tol or
               abs(y - k["geometry"]["coordinates"][1]) > tol for k in kept):
            kept.append(f)
    return kept


def validate_and_summarise(chargers, cands, demand):
    rows = []
    for name, feats in (("existing_chargers", chargers), ("candidate_sites", cands), ("demand_points", demand)):
        coords = [f["geometry"]["coordinates"] for f in feats]
        missing = sum(1 for c in coords if c is None or None in c)
        dup = len(coords) - len({tuple(c) for c in coords})
        rows.append({"dataset": name, "count": len(feats), "missing_coords": missing, "duplicate_coords": dup,
                     "source": feats[0]["properties"].get("source", "") if feats else ""})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm", action="store_true", help="download real OSM data (needs osmnx + internet)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    os.makedirs(PROCESSED, exist_ok=True)
    if args.osm:
        chargers, cands, demand = download_osm()
        if not demand or not cands:
            print("OSM returned no usable data; aborting.", file=sys.stderr)
            return 1
    else:
        chargers, cands, demand = generate_synthetic(seed=args.seed)

    _write_geojson(os.path.join(PROCESSED, "existing_chargers.geojson"), chargers)
    _write_geojson(os.path.join(PROCESSED, "candidate_sites.geojson"), cands)
    _write_geojson(os.path.join(PROCESSED, "demand_points.geojson"), demand)
    rows = validate_and_summarise(chargers, cands, demand)
    with open(os.path.join(PROCESSED, "data_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
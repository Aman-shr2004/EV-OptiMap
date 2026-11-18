# EV-OptiMap: EV Charging Station Optimal Placement (Indore)

GIS-based decision-support prototype that recommends where to add new EV charging stations by maximizing
**weighted demand coverage** (Maximum Coverage Location Problem), given existing chargers, a coverage radius
and a station budget.

## Quick start

```bash
pip install -r requirements.txt
python data_collection/download_osm.py        # synthetic demo data (works offline)
python app.py                                  # open http://127.0.0.1:5000
python -m pytest                               # run tests
```

For real data (needs internet, osmnx + geopandas):

```bash
python data_collection/download_osm.py --osm
```

If no data exists when the app starts, synthetic demo data is generated automatically.
**Synthetic data is for demo/testing only; do not report it as real Indore data.**

## How it works

1. `data_collection/download_osm.py` builds `existing_chargers.geojson`, `candidate_sites.geojson`,
   `demand_points.geojson` and `data_summary.csv` in `data/processed/`.
2. `optimizer/demand.py` loads points and demand weights (residential 1.0, commercial 3.0, parking 2.5, public 2.0 are
   configurable project assumptions).
3. `optimizer/distance.py` computes haversine (straight-line) distances.
4. Existing chargers are fixed coverage; `optimizer/greedy.py` repeatedly picks the candidate covering the most
   still-uncovered weight. A random baseline (mean/best/worst over 200 trials) is computed with the same metric.
5. `optimizer/evaluation.py` reports weighted coverage, uncovered demand, average distance, improvement over
   baseline, station count and estimated cost.
6. `app.py` serves the Leaflet map, JSON APIs, CSV export; runs are stored in SQLite (`data/runs.db`).

## Metrics

Weighted demand coverage = covered weight / total weight x 100. This is an estimate based on proxy data, **not**
population or EV coverage.

## Limitations (include in your report)

- Demand is a proxy (OSM POIs/landuse), not EV registrations or charging sessions.
- Straight-line distance, not road-network distance (future work: OSMnx shortest paths).
- Candidate sites are not verified for land, grid capacity or permissions; outputs are recommended candidates, not approved sites.
- Radius (default 2 km), K and costs are configurable assumptions, not local standards.
- OSM charger data may be incomplete; verify the downloaded count.
- Greedy gives a (1 - 1/e) approximation guarantee for max coverage but is not guaranteed optimal.
  An exact ILP (OR-Tools / SciPy `milp`) is a possible extension.

## Structure

```
app.py  requirements.txt  README.md
data/{raw,processed}  optimizer/  data_collection/  database/  templates/  static/  tests/
```
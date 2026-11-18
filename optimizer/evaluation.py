"""Metrics and the end-to-end optimisation run."""
import numpy as np

from .distance import haversine_matrix, nearest_distance
from .greedy import cover_matrix, greedy_max_coverage, random_baseline


def coverage_metrics(weights, dist_to_nearest, radius_km):
    total = float(np.sum(weights))
    covered_mask = dist_to_nearest <= radius_km
    covered = float(np.sum(weights[covered_mask]))
    finite = dist_to_nearest[np.isfinite(dist_to_nearest)]
    avg = float(np.mean(finite)) if len(finite) else None
    return {
        "total_demand": total,
        "covered_demand": covered,
        "uncovered_demand": total - covered,
        "weighted_coverage_pct": (100.0 * covered / total) if total > 0 else 0.0,
        "avg_distance_km": avg,
    }


def run_optimization(data, k=10, radius_km=2.0, cost_per_station=None, budget=None,
                     category_weights=None, random_trials=200, seed=0):
    """Run greedy + random baseline. `data` is the dict from demand.load_dataset."""
    from .demand import demand_weights

    demand, cands, chargers = data["demand"], data["candidates"], data["chargers"]
    if len(demand) == 0 or len(cands) == 0:
        raise ValueError("Dataset has no demand points or candidate sites.")
    if radius_km <= 0:
        raise ValueError("radius_km must be positive.")
    k = int(k)
    if k < 0:
        raise ValueError("k must be >= 0.")
    # optional cost limit reduces the station budget
    if cost_per_station and budget:
        k = min(k, int(budget // cost_per_station))

    w = demand_weights(data["demand_props"], category_weights)
    d_dc = haversine_matrix(demand, cands)
    cover = cover_matrix(d_dc, radius_km)
    d_exist = nearest_distance(demand, chargers)
    already = d_exist <= radius_km

    sel, gains = greedy_max_coverage(w, cover, already, k)
    rnd = random_baseline(w, cover, already, k, trials=random_trials, seed=seed)

    before = coverage_metrics(w, d_exist, radius_km)
    d_new = d_dc[:, sel].min(axis=1) if sel else np.full(len(demand), np.inf)
    after = coverage_metrics(w, np.minimum(d_exist, d_new), radius_km)

    rsel = rnd["best_selection"]
    d_r = d_dc[:, rsel].min(axis=1) if rsel else np.full(len(demand), np.inf)
    rnd_avg_dist = coverage_metrics(w, np.minimum(d_exist, d_r), radius_km)["avg_distance_km"]
    rnd_mean_pct = 100.0 * rnd["mean"] / after["total_demand"] if after["total_demand"] else 0.0

    selected = []
    for rank, (j, g) in enumerate(zip(sel, gains), start=1):
        selected.append({"rank": rank, "candidate_id": int(j),
                         "lat": float(cands[j][0]), "lon": float(cands[j][1]),
                         "new_demand_covered": g,
                         "cost": cost_per_station})
    est_cost = cost_per_station * len(sel) if cost_per_station else None

    return {
        "params": {"k": k, "radius_km": radius_km, "cost_per_station": cost_per_station, "budget": budget},
        "existing_coverage": before,
        "greedy": {**after, "stations": len(sel), "estimated_cost": est_cost},
        "random_baseline": {"mean_coverage_pct": rnd_mean_pct,
                            "best_coverage_pct": 100.0 * rnd["best"] / after["total_demand"] if after["total_demand"] else 0.0,
                            "worst_coverage_pct": 100.0 * rnd["worst"] / after["total_demand"] if after["total_demand"] else 0.0,
                            "best_avg_distance_km": rnd_avg_dist, "trials": random_trials},
        "improvement_over_random_pct_points": after["weighted_coverage_pct"] - rnd_mean_pct,
        "selected": selected,
    }


def compare_budgets(data, budgets=(5, 10, 15), **kw):
    out = []
    for b in budgets:
        r = run_optimization(data, k=b, **kw)
        out.append({"k": b, "greedy_pct": r["greedy"]["weighted_coverage_pct"],
                    "random_mean_pct": r["random_baseline"]["mean_coverage_pct"],
                    "avg_distance_km": r["greedy"]["avg_distance_km"]})
    return out
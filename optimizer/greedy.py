"""Greedy maximum-coverage selection and random baseline."""
import numpy as np


def cover_matrix(dist_dc, radius_km):
    """Boolean (N demand x J candidates): candidate j covers demand i if d_ij <= R."""
    return dist_dc <= radius_km


def greedy_max_coverage(weights, cover, already_covered, k):
    """Pick up to k candidates, each time maximising newly covered weight.

    weights: (N,) demand weights
    cover: (N,J) bool
    already_covered: (N,) bool, covered by existing chargers
    Returns (selected list of candidate indices, gains list).
    """
    weights = np.asarray(weights, dtype=float)
    uncovered = ~np.asarray(already_covered, dtype=bool)
    cov_f = cover.astype(float)
    selected, gains = [], []
    chosen = np.zeros(cover.shape[1], dtype=bool)
    for _ in range(int(k)):
        gain = (weights * uncovered) @ cov_f
        gain[chosen] = -1.0
        j = int(np.argmax(gain)) if gain.size else -1
        if j < 0 or gain[j] <= 0:
            break  # nothing more to gain
        selected.append(j)
        gains.append(float(gain[j]))
        chosen[j] = True
        uncovered &= ~cover[:, j]
    return selected, gains


def random_baseline(weights, cover, already_covered, k, trials=200, seed=0):
    """Random K candidates; returns dict with mean/best/worst covered weight over trials."""
    rng = np.random.default_rng(seed)
    weights = np.asarray(weights, dtype=float)
    base = np.asarray(already_covered, dtype=bool)
    n_c = cover.shape[1]
    k = min(int(k), n_c)
    if k <= 0:
        covered = float(weights[base].sum())
        return {"mean": covered, "best": covered, "worst": covered, "best_selection": []}
    results, best_sel, best_val = [], [], -1.0
    for _ in range(trials):
        sel = rng.choice(n_c, size=k, replace=False)
        covered_mask = base | cover[:, sel].any(axis=1)
        val = float(weights[covered_mask].sum())
        results.append(val)
        if val > best_val:
            best_val, best_sel = val, sel.tolist()
    return {"mean": float(np.mean(results)), "best": float(np.max(results)),
            "worst": float(np.min(results)), "best_selection": best_sel}
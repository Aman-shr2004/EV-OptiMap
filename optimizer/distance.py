"""Distance helpers (straight-line / haversine, in km)."""
import numpy as np

EARTH_RADIUS_KM = 6371.0088


def haversine_matrix(a, b):
    """Pairwise haversine distance in km. a: (N,2) [lat,lon], b: (M,2). Returns (N,M)."""
    a = np.asarray(a, dtype=float).reshape(-1, 2)
    b = np.asarray(b, dtype=float).reshape(-1, 2)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    lat1 = np.radians(a[:, 0])[:, None]
    lon1 = np.radians(a[:, 1])[:, None]
    lat2 = np.radians(b[:, 0])[None, :]
    lon2 = np.radians(b[:, 1])[None, :]
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def nearest_distance(demand, stations):
    """Distance (km) from each demand point to its nearest station. inf if no stations."""
    if len(stations) == 0:
        return np.full(len(demand), np.inf)
    return haversine_matrix(demand, stations).min(axis=1)
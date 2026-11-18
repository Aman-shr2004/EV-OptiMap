"""SQLite storage for optimisation runs."""
import json
import os
import sqlite3
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "runs.db")


def _conn(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def init_db(path=None):
    with _conn(path) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            k INTEGER, radius_km REAL,
            greedy_pct REAL, random_mean_pct REAL,
            result_json TEXT NOT NULL)""")


def save_run(result, path=None):
    init_db(path)
    p = result["params"]
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO runs (created_at,k,radius_km,greedy_pct,random_mean_pct,result_json) VALUES (?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), p["k"], p["radius_km"],
             result["greedy"]["weighted_coverage_pct"], result["random_baseline"]["mean_coverage_pct"],
             json.dumps(result)))
        return cur.lastrowid


def list_runs(limit=50, path=None):
    init_db(path)
    with _conn(path) as c:
        rows = c.execute("SELECT id,created_at,k,radius_km,greedy_pct,random_mean_pct FROM runs "
                         "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id, path=None):
    init_db(path)
    with _conn(path) as c:
        r = c.execute("SELECT result_json FROM runs WHERE id=?", (run_id,)).fetchone()
    return json.loads(r["result_json"]) if r else None
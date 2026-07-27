"""
Polls Toronto's public bike share GBFS feed and stores a snapshot of
every station's bike/dock availability into a local SQLite database.

Run this on a schedule (cron, systemd timer, Task Scheduler, a loop -
see run_loop() at the bottom). In production this runs hourly via
PythonAnywhere's Scheduled Tasks (see SPEC.md SS3, SS8).

Data-quality filters applied at collection time (SPEC.md SS3):
  - Skip a station's snapshot if it reports is_renting=false or
    is_returning=false (temporarily out of service).
  - Skip a station's snapshot if its last_reported timestamp is more
    than an hour old at poll time (stale/stuck reading - recording it
    would just repeat one real observation as if it were many).

Usage:
    python poll_stations.py            # single poll, then exit
    python poll_stations.py --loop     # poll every 5 min forever (Ctrl+C to stop)
"""

import sqlite3
import time
import sys
import os
import urllib.request
import json
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bikeshare.db")
STATION_INFO_URL = "https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_information"
STATION_STATUS_URL = "https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_status"
POLL_INTERVAL_SECONDS = 300  # 5 minutes, only relevant to --loop for local testing
STALE_THRESHOLD_SECONDS = 3600  # 1 hour


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "bikeshare-station-utility-poller/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            station_id TEXT PRIMARY KEY,
            name TEXT,
            lat REAL,
            lon REAL,
            capacity INTEGER,
            is_charging_station INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS status_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT,
            polled_at TEXT,
            last_reported INTEGER,
            bikes_available INTEGER,
            docks_available INTEGER,
            is_renting INTEGER,
            is_returning INTEGER,
            status TEXT
        )
    """)
    # Natural-key uniqueness: prevents duplicate rows if the poller is
    # ever accidentally triggered twice for the same cycle.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_snap_unique
        ON status_snapshots(station_id, polled_at)
    """)
    conn.commit()


def upsert_stations(conn, station_info):
    rows = [
        (s["station_id"], s.get("name"), s.get("lat"), s.get("lon"),
         s.get("capacity"), int(s.get("is_charging_station", False)))
        for s in station_info["data"]["stations"]
    ]
    conn.executemany("""
        INSERT INTO stations (station_id, name, lat, lon, capacity, is_charging_station)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(station_id) DO UPDATE SET
            name=excluded.name, lat=excluded.lat, lon=excluded.lon,
            capacity=excluded.capacity,
            is_charging_station=excluded.is_charging_station
    """, rows)
    conn.commit()


def insert_snapshot(conn, station_status):
    polled_at_dt = datetime.now(timezone.utc)
    polled_at = polled_at_dt.isoformat()
    now_ts = polled_at_dt.timestamp()

    rows = []
    skipped_not_installed = 0
    skipped_not_renting = 0
    skipped_stale = 0

    for s in station_status["data"]["stations"]:
        if s.get("is_installed") != 1:
            skipped_not_installed += 1
            continue

        if not s.get("is_renting", True) or not s.get("is_returning", True):
            skipped_not_renting += 1
            continue

        last_reported = s.get("last_reported")
        if last_reported is not None and (now_ts - last_reported) > STALE_THRESHOLD_SECONDS:
            skipped_stale += 1
            continue

        rows.append((
            s["station_id"], polled_at, last_reported,
            s.get("num_bikes_available", 0), s.get("num_docks_available", 0),
            int(s.get("is_renting", True)), int(s.get("is_returning", True)),
            s.get("status", "UNKNOWN"),
        ))

    conn.executemany("""
        INSERT OR IGNORE INTO status_snapshots
        (station_id, polled_at, last_reported, bikes_available, docks_available,
         is_renting, is_returning, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    return len(rows), skipped_not_installed, skipped_not_renting, skipped_stale


def poll_once(conn):
    info = fetch_json(STATION_INFO_URL)
    status = fetch_json(STATION_STATUS_URL)
    upsert_stations(conn, info)
    n, skipped_not_installed, skipped_not_renting, skipped_stale = insert_snapshot(conn, status)
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] stored {n} snapshots "
        f"(skipped: {skipped_not_installed} not installed, "
        f"{skipped_not_renting} not renting/returning, "
        f"{skipped_stale} stale)"
    )


def run_loop(conn):
    print(f"Polling every {POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.")
    while True:
        try:
            poll_once(conn)
        except Exception as e:
            print(f"Poll failed: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    if "--loop" in sys.argv:
        run_loop(conn)
    else:
        poll_once(conn)
    conn.close()

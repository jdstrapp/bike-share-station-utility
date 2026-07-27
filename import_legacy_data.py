"""
One-time (and re-runnable) import of historical snapshots collected by
the earlier bikeshare-tracker prototype into this project's bikeshare.db.

Safe to re-run: status_snapshots are deduplicated on (station_id,
polled_at), so running this again after the legacy poller has collected
more data will only add the new rows, not duplicate existing ones.

Usage:
    python import_legacy_data.py [path_to_legacy_bikeshare.db]

    (defaults to ../bikeshare-tracker/bikeshare.db, i.e. a sibling
    project folder)
"""

import sqlite3
import sys
import os

DEFAULT_LEGACY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bikeshare-tracker", "bikeshare.db"
)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bikeshare.db")


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
    # Natural-key uniqueness so re-running this import (or the future
    # poller double-firing) can't create duplicate snapshots.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_snap_unique
        ON status_snapshots(station_id, polled_at)
    """)
    conn.commit()


def main():
    legacy_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LEGACY_PATH)
    if not os.path.exists(legacy_path):
        print(f"Legacy database not found at: {legacy_path}")
        sys.exit(1)

    dest = sqlite3.connect(DB_PATH)
    init_db(dest)

    src = sqlite3.connect(legacy_path)
    src.row_factory = sqlite3.Row

    stations = src.execute("SELECT * FROM stations").fetchall()
    dest.executemany("""
        INSERT INTO stations (station_id, name, lat, lon, capacity, is_charging_station)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(station_id) DO UPDATE SET
            name=excluded.name, lat=excluded.lat, lon=excluded.lon,
            capacity=excluded.capacity, is_charging_station=excluded.is_charging_station
    """, [(s["station_id"], s["name"], s["lat"], s["lon"], s["capacity"], s["is_charging_station"]) for s in stations])

    snapshots = src.execute("""
        SELECT station_id, polled_at, last_reported, bikes_available,
               docks_available, is_renting, is_returning, status
        FROM status_snapshots
    """).fetchall()

    before = dest.execute("SELECT COUNT(*) FROM status_snapshots").fetchone()[0]

    dest.executemany("""
        INSERT OR IGNORE INTO status_snapshots
        (station_id, polled_at, last_reported, bikes_available, docks_available,
         is_renting, is_returning, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [tuple(s) for s in snapshots])
    dest.commit()

    after = dest.execute("SELECT COUNT(*) FROM status_snapshots").fetchone()[0]

    print(f"Imported/updated {len(stations)} stations.")
    print(f"Snapshots: {before} before -> {after} after "
          f"({after - before} new, {len(snapshots) - (after - before)} already present).")

    src.close()
    dest.close()


if __name__ == "__main__":
    main()

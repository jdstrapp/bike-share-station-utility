"""
Flask app serving the Bike Share Station Utility dashboard and map.
Reads bikeshare.db directly and exposes JSON endpoints plus the
dashboard and map pages. See SPEC.md for the full design.

Each snapshot (daytime hours, 6am-midnight Toronto time inclusive) is
classified into one of 5 ABSOLUTE bands based on actual bike/dock counts
(not percentile rank), ordered left-to-right from "empty of bikes" to
"empty of docks":
  0 - No Bikes       bikes_available  <= 1
  1 - Limited Bikes   bikes_available  2-3
  2 - Just Right      bikes_available >= 4 AND docks_available >= 4
  3 - Limited Spaces  docks_available  2-3
  4 - No Spaces       docks_available <= 1
Each station's map color is whichever band it lands in MOST OFTEN (its
mode) across its daytime snapshots.

Stations with capacity <= 0 are excluded entirely (data-quality guard -
see SPEC.md SS4).
"""

from flask import Flask, jsonify, render_template
import sqlite3
import os
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bikeshare.db")

LOCAL_TZ = ZoneInfo("America/Toronto")
DAYTIME_START_HOUR = 6   # 6am
DAYTIME_END_HOUR = 24    # midnight, inclusive of the full 11pm hour (hour is always < 24)

# The poller runs once per hour, so recomputing this from scratch on
# every single page load / request is wasted work - it can only change
# once an hour anyway. Cache the expensive full-table scan+classify
# pass and only redo it if it's older than this many seconds.
CACHE_TTL_SECONDS = 600  # 10 minutes
_cache = {"computed_at": 0, "per_station": None}

# The poller runs once per hour (PythonAnywhere scheduled task), so
# each snapshot represents ~1 hour. Used to convert snapshot counts
# into approximate hours for the per-station popup histogram.
SNAPSHOT_INTERVAL_HOURS = 1

MIN_SNAPSHOTS = 5  # minimum daytime snapshots before a station counts toward anything

# Band index 0-4, left-to-right order: No Bikes -> Limited Bikes ->
# Just Right -> Limited Spaces -> No Spaces
BAND_LABELS = [
    "No Bikes",
    "Limited Bikes",
    "Just Right",
    "Limited Spaces",
    "No Spaces",
]
BAND_COLORS = [
    "#dc2626",  # dark red   - No Bikes (<=1 bike)
    "#f97316",  # orange     - Limited Bikes (2-3 bikes)
    "#16a34a",  # green      - Just Right (4+ bikes and 4+ docks)
    "#93c5fd",  # light blue - Limited Spaces (2-3 docks)
    "#1e40af",  # dark blue  - No Spaces (<=1 dock)
]

# "Distribution of Empty Stations" histogram buckets: percent of
# daytime snapshots a station spent in the "No Bikes" band, bucketed in
# 10% increments, highest-severity first (left to right).
EMPTY_DISTRIBUTION_BUCKET_LABELS = [
    ">90%", "80-90%", "70-80%", "60-70%", "50-60%",
    "40-50%", "30-40%", "20-30%", "10-20%", "0-10%",
]


def classify_band(bikes_available, docks_available):
    """5-band ABSOLUTE classification used for the map, popup histogram,
    and popup bar colors. Returns band index 0-4 (see BAND_LABELS/
    BAND_COLORS above for what each index means).

    Severe = 0-1 available, Moderate = 2-3 available, Just Right
    requires 4+ on both sides at once.
    """
    if bikes_available <= 1:
        empty_band = 0
    elif bikes_available <= 3:
        empty_band = 1
    else:
        empty_band = None

    if docks_available <= 1:
        full_band = 4
    elif docks_available <= 3:
        full_band = 3
    else:
        full_band = None

    if empty_band is None and full_band is None:
        return 2  # Just Right

    if empty_band is not None and full_band is None:
        return empty_band
    if full_band is not None and empty_band is None:
        return full_band

    # Both conditions apply at once - happens on small-capacity stations
    # where bikes_available and docks_available are both low at the same
    # time. Pick whichever is farther from "Just Right" (more severe);
    # break ties by whichever raw count is lower.
    dist_empty = 2 - empty_band
    dist_full = full_band - 2
    if dist_empty > dist_full:
        return empty_band
    if dist_full > dist_empty:
        return full_band
    return empty_band if bikes_available <= docks_available else full_band


def get_earliest_date_str():
    """Returns e.g. 'July 22' - the date of the very first snapshot
    ever recorded, in Toronto local time."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT MIN(polled_at) AS earliest FROM status_snapshots").fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    utc_dt = datetime.fromisoformat(row[0])
    local_dt = utc_dt.astimezone(LOCAL_TZ)
    return f"{local_dt.strftime('%B')} {local_dt.day}"


def _load_and_classify_all_snapshots():
    """The one expensive DB pass: reads every daytime snapshot for
    every station with capacity > 0, and classifies it both ways
    (binary Too Empty/Too Full, and 5-band). Returns
    {station_id: {...}} - shared source data for both the dashboard
    tables and the map/histogram, so we only touch the DB and loop over
    every row once, not twice."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.station_id, st.name, st.lat, st.lon,
               s.polled_at, s.bikes_available, s.docks_available
        FROM status_snapshots s
        JOIN stations st ON st.station_id = s.station_id
        WHERE st.lat IS NOT NULL AND st.lon IS NOT NULL
          AND st.capacity IS NOT NULL AND st.capacity > 0
    """).fetchall()
    conn.close()

    per_station = {}

    for r in rows:
        try:
            utc_dt = datetime.fromisoformat(r["polled_at"])
        except ValueError:
            continue
        local_dt = utc_dt.astimezone(LOCAL_TZ)

        if not (DAYTIME_START_HOUR <= local_dt.hour < DAYTIME_END_HOUR):
            continue

        entry = per_station.setdefault(r["station_id"], {
            "name": r["name"],
            "lat": r["lat"],
            "lon": r["lon"],
            "bands": [],
        })
        entry["bands"].append(classify_band(r["bikes_available"], r["docks_available"]))

    return per_station


def get_per_station_data():
    """Returns the cached per-station data, recomputing only if the
    cache is missing or older than CACHE_TTL_SECONDS."""
    now = time.time()
    if _cache["per_station"] is None or (now - _cache["computed_at"]) > CACHE_TTL_SECONDS:
        _cache["per_station"] = _load_and_classify_all_snapshots()
        _cache["computed_at"] = now
    return _cache["per_station"]


def compute_map_bands(per_station):
    """Each station's most common (mode) 5-band classification across
    its own daytime snapshots. Used for the map, the "Most Empty/Full
    Stations" tables, and the "Distribution of Empty Stations"
    histogram."""
    results = []
    for station_id, data in per_station.items():
        bands = data["bands"]
        n = len(bands)
        if n < MIN_SNAPSHOTS:
            continue

        counts = Counter(bands)
        mode_band, mode_count = counts.most_common(1)[0]

        pct_by_band = {i: round(100 * counts.get(i, 0) / n, 1) for i in range(5)}

        results.append({
            "station_id": station_id,
            "name": data["name"],
            "lat": data["lat"],
            "lon": data["lon"],
            "n_daytime_snapshots": n,
            "band_index": mode_band,
            "band_label": BAND_LABELS[mode_band],
            "color": BAND_COLORS[mode_band],
            "mode_pct": round(100 * mode_count / n, 1),
            "pct_no_bikes": pct_by_band[0],
            "pct_limited_bikes": pct_by_band[1],
            "pct_just_right": pct_by_band[2],
            "pct_limited_spaces": pct_by_band[3],
            "pct_no_spaces": pct_by_band[4],
        })

    return results


def compute_band_histogram(map_results):
    """Counts how many stations have each band as their dominant (mode)
    classification. Returns list aligned with BAND_LABELS/BAND_COLORS,
    already in left-to-right (No Bikes -> No Spaces) order."""
    counts = Counter(r["band_index"] for r in map_results)
    return [
        {"band_index": i, "label": BAND_LABELS[i], "color": BAND_COLORS[i], "count": counts.get(i, 0)}
        for i in range(5)
    ]


def compute_empty_distribution_histogram(map_results):
    """"Distribution of Empty Stations": how many stations fall into
    each bucket of what percent of their daytime snapshots landed in
    the "No Bikes" band, bucketed in 10% increments from >90%
    (most chronically empty) down to 0-10%."""
    buckets = [0] * 10
    for r in map_results:
        pct = r["pct_no_bikes"]
        idx = min(9, int((100 - pct) // 10))
        buckets[idx] += 1
    return [
        {"label": EMPTY_DISTRIBUTION_BUCKET_LABELS[i], "count": buckets[i]}
        for i in range(10)
    ]


def compute_top_lists(map_results, top_n=15):
    """"Most Empty Stations" / "Most Full Stations": ranked by percent
    of daytime snapshots in the "No Bikes" / "No Spaces" bands
    respectively - the same strict (<=1) threshold used by the
    Distribution of Empty Stations histogram, so a station ranks
    consistently across both views."""
    most_empty = sorted(map_results, key=lambda r: r["pct_no_bikes"], reverse=True)[:top_n]
    most_full = sorted(map_results, key=lambda r: r["pct_no_spaces"], reverse=True)[:top_n]
    return most_empty, most_full


def compute_station_histogram(station_id):
    """Per-bike-count histogram for one station: for each possible
    bikes_available value from 0 to capacity, how many daytime hours
    (approx.) the station spent at that exact count. Each bar is
    colored using classify_band(bikes, capacity - bikes)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    station_row = conn.execute(
        "SELECT name, capacity FROM stations WHERE station_id = ?", (station_id,)
    ).fetchone()

    if not station_row:
        conn.close()
        return None

    capacity = station_row["capacity"]

    if not capacity or capacity <= 0:
        conn.close()
        return {
            "station_id": station_id,
            "name": station_row["name"],
            "capacity": None,
            "n_daytime_snapshots": 0,
            "bars": [],
        }

    rows = conn.execute(
        "SELECT polled_at, bikes_available FROM status_snapshots WHERE station_id = ?",
        (station_id,)
    ).fetchall()
    conn.close()

    counts = [0] * (capacity + 1)
    n = 0
    for r in rows:
        try:
            utc_dt = datetime.fromisoformat(r["polled_at"])
        except ValueError:
            continue
        local_dt = utc_dt.astimezone(LOCAL_TZ)
        if not (DAYTIME_START_HOUR <= local_dt.hour < DAYTIME_END_HOUR):
            continue

        # Clamp rare attendant-overflow snapshots (bikes > capacity)
        # into the rightmost bar so the axis stays 0..capacity.
        bikes_clamped = max(0, min(r["bikes_available"], capacity))
        counts[bikes_clamped] += 1
        n += 1

    bars = []
    for x in range(capacity + 1):
        slots_remaining = capacity - x
        band_index = classify_band(x, slots_remaining)
        bars.append({
            "bikes": x,
            "hours": round(counts[x] * SNAPSHOT_INTERVAL_HOURS, 1),
            "color": BAND_COLORS[band_index],
            "label": BAND_LABELS[band_index],
        })

    return {
        "station_id": station_id,
        "name": station_row["name"],
        "capacity": capacity,
        "n_daytime_snapshots": n,
        "bars": bars,
    }


@app.route("/api/summary")
def api_summary():
    per_station = get_per_station_data()
    map_results = compute_map_bands(per_station)

    most_empty, most_full = compute_top_lists(map_results)
    band_histogram = compute_band_histogram(map_results)
    empty_distribution_histogram = compute_empty_distribution_histogram(map_results)

    return jsonify({
        "most_empty_stations": most_empty,
        "most_full_stations": most_full,
        "band_histogram": band_histogram,
        "empty_distribution_histogram": empty_distribution_histogram,
        "total_stations": len(map_results),
        "earliest_date": get_earliest_date_str(),
    })


@app.route("/api/utility_map")
def api_utility_map():
    per_station = get_per_station_data()
    results = compute_map_bands(per_station)
    return jsonify({
        "stations": results,
        "total_stations": len(results),
        "band_labels": BAND_LABELS,
        "band_colors": BAND_COLORS,
        "earliest_date": get_earliest_date_str(),
    })


@app.route("/api/station_histogram/<station_id>")
def api_station_histogram(station_id):
    result = compute_station_histogram(station_id)
    if result is None:
        return jsonify({"error": "station not found"}), 404
    return jsonify(result)


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/map")
def utility_map():
    return render_template("map.html")


if __name__ == "__main__":
    app.run(debug=True)

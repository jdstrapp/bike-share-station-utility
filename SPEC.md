# Bike Share Station Utility — Spec

Status: Draft v1 (from interview on 2026-07-27)

## 1. Purpose

A public website that tracks Bike Share Toronto station availability over
time and answers: **which stations are chronically underserved — either
running empty of bikes or empty of docks — and when?**

The primary lens is historical/aggregate pattern-finding, not a live
"right now" status board (though the map's data does update as new
snapshots come in).

- **Audience:** public (not just personal use)
- **System covered:** Bike Share Toronto only (single city, for now)
- **Multi-city support, user accounts, live/real-time view:** explicitly
  out of scope for v1

## 2. Data Source

Bike Share Toronto's public GBFS (General Bikeshare Feed Specification) feed:

- `station_information`: https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_information
  (static-ish: station id, name, lat/lon, capacity)
- `station_status`: https://tor.publicbikesystem.net/ube/gbfs/v1/en/station_status
  (live: bikes_available, docks_available, is_renting, is_returning, status)

**No historical backfill.** Toronto's Open Data portal only publishes
trip-level ridership data (individual trips: start/end station, start/end
time, duration), not point-in-time station occupancy history. GBFS itself
is a live-only feed with no historical archive. Confirmed decision:
**poll-forward only** — history accumulates starting from deployment day,
no attempt to reconstruct or simulate the past from trip data.

## 3. Data Collection

- A poller script fetches both GBFS endpoints and stores one snapshot per
  station.
- **Frequency: hourly**, run via PythonAnywhere's built-in Scheduled Tasks
  feature (free, included in the base plan — no extra cost). This trades
  data resolution (24 samples/day/station instead of up to 288 at a 5-min
  cadence) for simplicity: no need for PythonAnywhere's paid "Always-on
  tasks" feature.
- Storage: SQLite (`bikeshare.db`), two tables:
  - `stations` (station_id, name, lat, lon, capacity, is_charging_station)
  - `status_snapshots` (station_id, polled_at UTC ISO timestamp,
    last_reported, bikes_available, docks_available, is_renting,
    is_returning, status)
- All time-based analysis is done in **America/Toronto** local time,
  converted from the stored UTC timestamps at query/analysis time.
- **Daytime window:** 6:00am–11:59pm local time ("cycling hours").
  Overnight snapshots (midnight–6am) are excluded from all classification,
  histograms, and heatmaps.

## 4. Classification System

Every daytime snapshot is classified into exactly one of 5 **absolute**
bands, based on raw bike/dock counts (not percentile rank across stations):

| # | Band | Condition | Color |
|---|------|-----------|-------|
| 0 | No Bikes | `bikes_available <= 1` | Dark red |
| 1 | Limited Bikes | `bikes_available` 2–3 | Orange |
| 2 | Just Right | `bikes_available >= 4` AND `docks_available >= 4` | Green |
| 3 | Limited Spaces | `docks_available` 2–3 | Light blue |
| 4 | No Spaces | `docks_available <= 1` | Dark blue / purple |

If a station is small enough that both a bike-side and dock-side
condition apply simultaneously, use whichever is more severe (farther
from "Just Right" in band-distance); tie-break by whichever raw count
(bikes vs docks) is lower.

A station's **map color** = the band it lands in most often (the mode)
across all its daytime snapshots collected so far. Stations need a
minimum sample size (5+ daytime snapshots) before they're included in
any ranking or the map, to avoid noisy single-observation results.

## 5. Map Page

- One marker per station, placed at its lat/lon, colored by its mode
  band (table above).
- Renderer: **Leaflet.js** (free, open-source, no API key required —
  appropriate for a public site with no ongoing map-vendor cost).
- **Clicking a marker opens a popup showing:**
  - Station name
  - A histogram: x-axis = bike count from 0 to the station's capacity;
    y-axis = number of daytime hours observed at that exact count. Each
    bar is colored using the same band classification applied to that
    x-axis value (e.g. the bar at "0 bikes" is dark red).
  - Only daytime (6am–midnight) snapshots feed this histogram.
  - A per-station hour × day-of-week heatmap (see §6).

## 6. Dashboard (Landing Page)

- **Band histogram:** 5 bars, one per band, height = number of stations
  whose *mode* band is that one. Gives an at-a-glance system health view.
- **Worst for empty:** ranked list of stations by how often they land in
  the "No Bikes" / "Limited Bikes" bands (top N, e.g. 15).
- **Worst for full:** ranked list of stations by how often they land in
  "No Spaces" / "Limited Spaces" (top N).
- **System-wide hour × day-of-week heatmap:** aggregated across all
  stations — reveals patterns like "system-wide, weekday mornings around
  8am are the worst time for bike availability."
- **Per-station hour × day-of-week heatmap:** available when drilling
  into an individual station (reachable from the worst-of lists or the
  map popup) — same idea, scoped to one station.
- Each list/summary should show total station count and the "since"
  earliest snapshot date, so viewers understand how much data backs the
  numbers (a fresh deployment will have thin history at first).

## 7. Tech Stack

- **Backend:** Python + Flask
- **Database:** SQLite (single file, adequate for this write volume —
  one hourly batch insert — and read-mostly query pattern)
- **Frontend:** Jinja2-rendered templates + vanilla JS; Leaflet.js for
  the map; a lightweight charting approach (plain Canvas/SVG or a small
  library) for histograms and the heatmap — finalized during
  implementation.

## 8. Hosting & Deployment

- **Host: PythonAnywhere**, paid tier (at least "Hacker," ~$5/month).
  Chosen over the free tier because the free tier (a) restricts outbound
  internet access to a domain whitelist that almost certainly excludes
  Toronto's GBFS feed host, and (b) serves web requests one at a time,
  which causes visible UI stalls on a public multi-visitor site.
- Web app served as a PythonAnywhere Flask web app (WSGI).
- Poller run via PythonAnywhere's built-in **Scheduled Tasks** (hourly),
  not an always-on process.
- **Domain:** free `yourusername.pythonanywhere.com` subdomain to start.
  A custom domain is possible later but requires PythonAnywhere's higher
  "Web Developer" tier (~$12/month) plus purchasing a domain (~$10–15/yr).
- Exact current PythonAnywhere pricing/plan features should be
  double-checked against pythonanywhere.com at deploy time, since these
  terms change.

## 9. Repository

- GitHub repo: `bike-share-station-utility`, **public** visibility.
- Local path: sibling folder to the earlier `bikeshare-tracker`
  prototype (this is a fresh project, not a continuation of that code).

## 10. Explicitly Out of Scope (v1)

- Historical backfill/import of pre-launch occupancy data (no source
  data exists for this).
- Multi-city / multi-system support.
- User accounts, personalization, alerts/notifications.
- A live "right now" single-moment status view (focus is historical
  patterns).

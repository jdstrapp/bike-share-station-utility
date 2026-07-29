# Bike Share Station Utility — Spec

Status: **Draft v2 — under review, not yet approved for implementation.**
v1 (as deployed to production 2026-07-28) is archived at
[archive/SPEC_v1.md](archive/SPEC_v1.md). Everything below is subject to
change until reviewed and explicitly approved to start coding.

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

**No official historical archive.** Toronto's Open Data portal only
publishes trip-level ridership data (individual trips: start/end station,
start/end time, duration), not point-in-time station occupancy history.
GBFS itself is a live-only feed with no historical archive of its own.

**But: self-collected head start.** An earlier prototype has been polling
this same feed hourly since 2026-07-22 and is still running, currently at
105,329+ status snapshots across 1,054 stations. That data's schema
(`stations` / `status_snapshots`) matches this project's needs exactly,
so at **cutover time** (once this project's own app is built and ready to
go live) it will be imported wholesale via `import_legacy_data.py` —
written now, but deliberately not run yet. The script is safe to re-run
(deduplicates on `(station_id, polled_at)`), so the legacy poller can
keep collecting right up until cutover without any risk of double-import.
Until then, the legacy project and its database are left untouched.

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
- **Daytime window:** 6:00am through midnight, **inclusive** — i.e. up
  through and including 11:59:59pm, the moment just before the clock
  rolls over. Overnight snapshots (midnight–6am) are excluded from all
  classification and histograms.
- **Skip snapshots from stations not actually renting/returning:** if a
  station reports `is_renting = false` or `is_returning = false`, the
  poller does not store a snapshot for it that cycle — these represent a
  station temporarily out of service (e.g. under maintenance), not real
  availability data.
- **Skip stale readings:** each station's `last_reported` field reflects
  when the station itself last communicated with Bike Share Toronto's
  backend — independent of when we polled. If `last_reported` is more
  than 1 hour old at poll time, the snapshot is skipped rather than
  stored. Without this check, a station stuck not-reporting for hours
  would have its one real last-known reading recorded over and over as
  if it were fresh new observations, skewing its historical distribution
  toward whatever state it happened to be stuck in.

## 4. Classification System

**Stations with `capacity <= 0` are excluded entirely** — from
classification, the map, and dashboard rankings. This is a
data-quality guard: the legacy dataset already has a real example
(station 7442, Lonsdale Rd / Spadina Rd) that the feed reports as
`IN_SERVICE` and actively renting/returning, but with capacity 0 — almost
certainly a missing-data artifact in the feed rather than a genuine
zero-dock station. A capacity of 0 would otherwise force every snapshot
into "No Spaces" regardless of actual bikes/docks, which is misleading.

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

## 5. Pages

Nav bar has four items: **Dashboard**, **Utility Map**, **Empty Station
Map**, **Station History**. The first three are specced below (5a/5b);
Station History (5c) is new for v2 and its spec is being gathered
incrementally over the next few days — details TBD, filled in as they
arrive. No implementation starts until the whole v2 spec (including this
page) is reviewed and approved.

### 5a. Utility Map (`/map`)

- One marker per station, placed at its lat/lon, colored by its mode
  band (table above).
- Renderer: **Leaflet.js** (free, open-source, no API key required —
  appropriate for a public site with no ongoing map-vendor cost).
- **Clicking a marker opens a popup showing:**
  - Station name — **clickable**, same as the Dashboard's Most
    Empty/Full Stations tables (§6): links to the Station History page
    (§5c) with that station pre-selected.
  - A histogram: x-axis = bike count from 0 to the station's capacity;
    y-axis = number of daytime hours observed at that exact count. Each
    bar is colored using the same band classification applied to that
    x-axis value (e.g. the bar at "0 bikes" is dark red), and labeled
    with its raw observation count (number of hours) directly above the
    bar.
  - Only daytime (6am–midnight, inclusive) snapshots feed this histogram.
  - **Large-capacity stations:** the popup has a fixed display width of
    25 bars. For stations with capacity > 25, the histogram truncates to
    a scrollable/slider view instead of squeezing all bars into the same
    width — keeps individual bars readable regardless of station size.
- **Bug: popup auto-pan doesn't account for the page header.** For a
  marker near the top of the screen, clicking it opens a popup whose top
  (station name) is cut off/hidden, and the map doesn't pan far enough
  down to reveal it — user has to manually pan. Fix: account for the
  fixed header's height when Leaflet auto-pans to fit the popup (e.g.
  via `autoPanPaddingTopLeft`), not just its default padding.
- **Legend needs a title:** "Predominant Station Status" (currently just
  shows the 5 color swatches with no heading).

### 5b. Empty Station Map (`/empty-map`)

A second map, focused specifically on chronically-empty stations rather
than the full 5-band picture.

- Same Leaflet renderer, same base tiles.
- Each station colored by the **dark-red-to-orange gradient** (§6) based
  on what percent of its daytime snapshots landed in the "No Bikes" band
  (`bikes_available <= 1`) — same 6 severity buckets as the Distribution
  of Empty Stations histogram (`>90%` down to `40-50%`).
- **Stations below the 40% threshold** (i.e. not chronically empty
  enough to land in any of the 6 buckets) are rendered as **white-filled
  circles** with the same dark outline as colored markers — still
  visible/located on the map, but visually distinct from the gradient,
  so the chronically-empty stations pop out.
- Clicking a marker opens the same popup style as the Utility Map
  (station name + per-station histogram), **including**: the clickable
  station-name link to Station History (§5c), and the auto-pan fix for
  markers near the top of the screen — both apply here too, not just on
  the Utility Map.

### 5c. Station History (`/history` — TBD)

Being gathered incrementally. Known so far:

- Must support being linked to with a station pre-selected (from the
  Dashboard's Most Empty/Full Stations tables §6, and both maps' popup
  station-name links §5a/§5b).
- **Station picker** at the top of the page — a searchable picklist over
  1,000+ station names, since names aren't obvious (e.g. "Harvie Ave /
  Rogers Rd"). Search behavior, in scope now:
  - **Multi-word substring matching:** typing "Harvie" *or* "Rogers"
    (any word in the name, not just a prefix) matches "Harvie Ave /
    Rogers Rd". Local/client-side, no external dependency.
  - **Intersection-aware parsing:** most station names are formatted as
    "Street A / Street B". Strip filler words ("corner of", "and") from
    the query and match remaining terms against a station's two parsed
    street names — handles "corner of Harvie and Rogers".
  - Typo-tolerance (fuzzy matching) is a reasonable cheap add-on here,
    exact approach TBD at implementation time.
  - **Explicitly out of scope for now:** directional/proximity queries
    ("Rogers near Caledonia", "Rogers east of Dufferin") — needs real
    geographic reasoning and would be heuristic/unreliable at best; not
    worth the complexity relative to the payoff.
  - **Phase-2 candidate (not now):** neighborhood queries ("Rosedale" →
    list its stations). Feasible via a **one-time** import of Toronto
    Open Data's free neighborhood boundary polygons, precomputing which
    neighborhood each station falls into at import time — no ongoing
    cost or live external dependency, but real work to build. Revisit
    after the core picker ships.
- **Once a station is selected, show two graphs below the picker:**
  1. **Full-history line graph:** x-axis = **day and hour** (matches the
     hourly polling cadence), y-axis = **Bikes Available** or
     **Capacity** at that hour (both series share one y-axis), plotting
     **every observation ever recorded** for that
     station (from the first snapshot to the latest) — unlike the
     histograms elsewhere, this is **not** restricted to the daytime
     6am-midnight window; overnight data is included. Gaps in the data
     (missed polls, stale-skip periods, etc.) are left blank rather than
     interpolated/connected across — no line drawn where there's no
     data. A second, lighter-weight line shows station **capacity**
     over the same timeline, typically flat/horizontal since capacity
     rarely changes.
     - **Open caveat:** the current schema only stores each station's
       *current* capacity (overwritten on every poll via upsert), not a
       history of capacity changes. If a station's capacity actually
       changed over time, we can't currently reconstruct what it was at
       each past point — the capacity line could only be drawn as a
       flat line at today's known value, not a true historical line.
       Flagging this now; may need a schema change (e.g. only update
       stored capacity when it changes, with a timestamp) if accurate
       historical capacity turns out to matter.
  2. **Per-station bike-count histogram** — identical to the one shown
     in the Utility Map / Empty Station Map popups (§5a): x-axis = bike
     count 0 to capacity, y-axis = daytime hours observed at that count,
     bars colored by band, observation-count labels, scrollable past 25
     bars. Same data, just also surfaced here.
- Everything else — page layout, URL scheme — still TBD.

## 6. Dashboard (Landing Page)

- **"Station Utility Summary" (band histogram):** 5 bars, one per band,
  height = number of stations whose *mode* band is that one. Gives an
  at-a-glance system health view. Each bar's x-axis label shows the
  band name with its bike/dock-count range in brackets below it: "No
  Bikes (0-1)", "Limited Bikes (2-3)", "Just Right" (no range - it's a
  conjunction of both sides, not a single count range), "Limited Spaces
  (2-3)", "No Spaces (0-1)".
- **"Most Empty Stations":** ranked list of stations by percent of
  daytime snapshots in the "No Bikes" band (`bikes_available <= 1`) —
  matches the same threshold as the "Distribution of Empty Stations"
  histogram below, so a station ranks consistently across both views. Column
  titled **"% Time Empty"** (top N, e.g. 15).
- **"Most Full Stations":** ranked list of stations by percent of
  daytime snapshots in the "No Spaces" band (`docks_available <= 1`).
  Column titled **"% Time Full"** (top N).
- **Station names in both tables are clickable**, linking to the Station
  History page (§5c) with that station pre-selected. (Exact URL/query
  param scheme TBD alongside the rest of §5c's spec.)
- **"Distribution of Empty Stations" histogram:** how many stations fall
  into each bucket of what percent of their daytime snapshots landed in
  the "No Bikes" band (`bikes_available <= 1`). **Only shows the 6
  buckets from `>90%` down to `40-50%`** — stations below the 40%
  threshold are dropped from this chart entirely (they still count
  everywhere else, just not here). Ordered left-to-right from
  most-chronically-empty to least. Bar height = number of stations
  falling in that bucket, colored with a **dark-red -> red -> orange ->
  yellow gradient** (darkest red at `>90%`, fading to yellow at
  `40-50%`) rather than a single flat color. Widened from an initial
  red-to-orange-only gradient that read as visually indistinct on the
  small Empty Station Map markers — sweeping across more hue (not just
  lightness) separates the 6 severity levels much more clearly. Same
  gradient/bucketing reused for the Empty Station Map (§5b). Surfaces
  the handful of stations that are essentially *always* empty, not just
  "often" empty — a sharper cut
  than the ranked list above.
- Each list/summary should show total station count and the "since"
  earliest snapshot date, so viewers understand how much data backs the
  numbers (a fresh deployment will have thin history at first).

Note: the hour × day-of-week heatmaps (both system-wide and per-station)
originally planned here are cut from v1 — may revisit later.

## 7. Tech Stack

- **Backend:** Python + Flask
- **Database:** SQLite (single file, adequate for this write volume —
  one hourly batch insert — and read-mostly query pattern)
- **Frontend:** Jinja2-rendered templates + vanilla JS; Leaflet.js for
  the map; a lightweight charting approach (plain Canvas/SVG or a small
  library) for histograms — finalized during implementation.

## 8. Hosting & Deployment

- **Host: PythonAnywhere**, paid tier (at least "Hacker," ~$5/month).
  Chosen over the free tier because the free tier (a) restricts outbound
  internet access to a domain whitelist that almost certainly excludes
  Toronto's GBFS feed host, and (b) serves web requests one at a time,
  which causes visible UI stalls on a public multi-visitor site.
- Web app served as a PythonAnywhere Flask web app (WSGI).
- Poller run via PythonAnywhere's built-in **Scheduled Tasks** (hourly),
  not an always-on process.
- **Domain:** free `yourusername.pythonanywhere.com` subdomain to start,
  with this app served under a path prefix — **`/BikeShareUtility`**
  (e.g. `yourusername.pythonanywhere.com/BikeShareUtility/`) — rather
  than at the subdomain root, so other future projects can live at other
  paths on the same account without conflicting.
  A custom domain is possible later but requires PythonAnywhere's higher
  "Web Developer" tier (~$12/month) plus purchasing a domain (~$10–15/yr).
- Exact current PythonAnywhere pricing/plan features should be
  double-checked against pythonanywhere.com at deploy time, since these
  terms change.

## 9. Repository

- GitHub repo: `bike-share-station-utility`, **public** visibility.
- Local path: sibling folder to the earlier `bikeshare-tracker`
  prototype. This is a fresh codebase, not a continuation of that
  project's code — but its `stations` / `status_snapshots` schema was
  reused as-is since it already matched this project's needs, and its
  collected data will be imported at cutover time (§2).
- The legacy `bikeshare-tracker` project and its database are left
  running and untouched until cutover. Once this project's own poller is
  deployed and confirmed working, run `import_legacy_data.py` one final
  time to pull in everything collected up to that point, then stop the
  legacy poller to avoid two processes polling the same feed
  independently.
- **Accepted tradeoff during the overlap period:** while both pollers
  run in parallel (legacy hourly poll + this project's new production
  poll), they'll each record their own snapshot at slightly different
  timestamps for what's roughly the same real-world hour. The
  `(station_id, polled_at)` dedup key won't catch these as true
  duplicates (the timestamps differ), so the merged history will have
  some near-duplicate/overlapping observations for that window. This is
  accepted as a minor, temporary data-quality wrinkle rather than
  something engineered around — it goes away once the legacy poller is
  stopped.

## 10. Explicitly Out of Scope (v1)

- Multi-city / multi-system support.
- User accounts, personalization, alerts/notifications.
- A live "right now" single-moment status view (focus is historical
  patterns).

# Bike Share Station Utility

A public dashboard and map tracking Bike Share Toronto station
availability over time, to surface which stations are chronically
underserved (running out of bikes or docks) and when.

See [SPEC.md](SPEC.md) for the full project spec.

## Status

Spec complete. Implementation in progress.

## Project layout (planned)

```
poll_stations.py       # hourly GBFS poller -> bikeshare.db
import_legacy_data.py  # one-time (re-runnable) import from the earlier
                        # bikeshare-tracker prototype's collected data
app.py                  # Flask app: dashboard + map + JSON APIs
templates/               # Jinja2 templates (dashboard.html, map.html)
static/                  # JS/CSS assets
bikeshare.db             # SQLite database (not committed; created at runtime)
```

## Local development

```
pip install -r requirements.txt
python poll_stations.py         # one poll, to seed the database
python app.py                   # runs the dashboard at http://localhost:5000
```

## Deployment

Hosted on PythonAnywhere. See SPEC.md §8 for the hosting plan.

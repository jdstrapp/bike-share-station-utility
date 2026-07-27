# Deploying to PythonAnywhere

Target: `https://jdstrapp.pythonanywhere.com/BikeShareUtility/`

## 1. Clone the repo

In a PythonAnywhere **Bash console** (Consoles tab -> Bash):

```
git clone https://github.com/jdstrapp/bike-share-station-utility.git
```

## 2. Create a virtualenv and install dependencies

```
mkvirtualenv --python=/usr/bin/python3.10 bikeshare-venv
pip install -r bike-share-station-utility/requirements.txt
```

(Check `ls /usr/bin/python3*` first if 3.10 isn't available and use whatever
3.x version PythonAnywhere offers.)

## 3. Seed the database once, manually

The app expects `bikeshare.db` to already have tables before it's served.
Run the poller once by hand to create it:

```
cd bike-share-station-utility
python poll_stations.py
```

This creates `bikeshare.db` with one real snapshot in it.

## 4. Configure the web app

In the **Web** tab:

1. "Add a new web app" (if none exists yet) -> choose **Manual configuration**
   (not a framework quick-setup) -> pick the same Python version as the
   virtualenv.
2. Under "Virtualenv", set it to: `/home/jdstrapp/.virtualenvs/bikeshare-venv`
3. Click the WSGI configuration file link and replace its contents with:

```python
import sys

path = '/home/jdstrapp/bike-share-station-utility'
if path not in sys.path:
    sys.path.insert(0, path)

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.exceptions import NotFound
from app import app as bikeshare_app

# Mounts this app under /BikeShareUtility so other future projects can
# live at other paths on the same domain later - just add more entries
# to this dict.
application = DispatcherMiddleware(NotFound(), {
    '/BikeShareUtility': bikeshare_app,
})
```

4. Click the green **Reload** button.
5. Visit `https://jdstrapp.pythonanywhere.com/BikeShareUtility/` and confirm
   the dashboard loads.

## 5. Set up hourly polling

In the **Tasks** tab, add a scheduled task (hourly, any minute past the hour)
running:

```
/home/jdstrapp/.virtualenvs/bikeshare-venv/bin/python /home/jdstrapp/bike-share-station-utility/poll_stations.py
```

(Full paths matter here - scheduled tasks don't run inside the virtualenv
automatically.)

Check the task's log after its first couple of runs to confirm it's storing
snapshots without errors.

## 6. Cutover (later, once the above has run reliably for a while)

Not done yet as of this writing - see SPEC.md SS2/SS9. When ready:

1. Upload the legacy project's `bikeshare.db` from your local machine to
   PythonAnywhere (Files tab, drag-and-drop, or `scp` if using SSH).
2. Run `python import_legacy_data.py /path/to/uploaded/bikeshare.db` on
   PythonAnywhere - it merges into the production db, deduplicating by
   `(station_id, polled_at)`.
3. Stop the legacy `bikeshare-tracker` poller.

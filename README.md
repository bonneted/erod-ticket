Event Queueing Flask App
=========================

A simple Flask app for managing a ticketing queue at an event.

Features:
- Main page that displays a waiting queue and a passed list.
- Estimates wait time per person based on the configured tour length.
- A register page (that can be linked with a QR code) to join the queue by entering a name.
- Automatic advancement when the tour time runs out (the server updates the queue on status fetches).
- Controls on the main page to advance (Next), go back (Back), pause/resume, and reorder the queue via drag-and-drop.

Quick start
-----------

1. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

2. Run the app

```powershell
python app.py
```

The app runs by default in debug mode on http://127.0.0.1:5000

Usage
-----

- Open the main page at / to view the queue and controls.
- Scan the QR code or visit /register to join the queue.
- Use Next/Back to move people and Pause to pause the timer.
- Click "Enable reorder" to change the waiting list order via drag-and-drop, then change is sent to the server.

Notes & Limitations
-------------------
- This app uses SQLite and persists data to `queue.db` in the project folder.
- No authentication is implemented; it's intended for an internal kiosk-style setup.
- The automatic advancement is triggered on `/api/status` calls (client polling) — there's no background scheduler.

Development
-----------
- Tests are in `tests/` using PyTest. Run them with `pytest -q`.

Deploying on Railway (GitHub)
-----------------------------

Railway makes it easy to deploy your app from a GitHub repository. Here's a brief guide:

1) Create a GitHub repo and push:

```powershell
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <git_remote_url>
git push -u origin main
```

2) Create a Railway project and connect GitHub

- Go to https://railway.app and sign in with GitHub.
- Create a new project and choose "Deploy from GitHub". Select your repository.
- Railway will read the repo and should detect the Python project. If needed, set the build command to:

	pip install -r requirements.txt

- Set the start command to use the Procfile; the default should pick `web: gunicorn --bind 0.0.0.0:$PORT app:app`.

3) Configure a persistent database (recommended)

- For a production deployment, prefer Railway's Postgres plugin rather than SQLite (SQLite data won't persist across deploys).
- In your Railway project's Plugins tab, add a Postgres plugin. Railway will add a `DATABASE_URL` environment variable to your project automatically.
- If your app uses `DATABASE_URL` (it does by default from the code), the app will automatically use PostgreSQL.

4) Env vars and ports

- Railway uses the `PORT` environment variable and the app will respect it. For non-Railway environments, keep using `sqlite:///queue.db` as a fallback.

5) Auto-deploy

- After connecting the repo, Railway can auto-deploy on push to the default branch (main). Your app will be reachable at the provided Railway URL.

Optional: Railway CLI quick flow
--------------------------------

If you prefer the CLI, install the Railway CLI and run:

```powershell
npm i -g railway
railway login
railway init  # select your GitHub repo
railway up    # deploy
railway plugin add postgres
```

Data migration example (SQLite -> Postgres)
------------------------------------------

If you already have data in `queue.db` and want to migrate to Postgres, export CSVs from SQLite and import into Postgres. For example:

```powershell
sqlite3 queue.db "headers on
.mode csv
.output persons.csv
SELECT id, name, status, position, added_at, passed_at FROM persons;"

# Import to Postgres (replace the conn string with your db details)
psql "<your_postgres_connection_string>" -c "\copy persons(id, name, status, position, added_at, passed_at) FROM 'persons.csv' CSV HEADER;"
```

Notes

- SQLite is fine for local development but not recommended for shared/production environments.
- Postgres is recommended; you can migrate SQLite data to Postgres if needed (via SQLAlchemy dump or manual migration).
- If you're using Railway Postgres, the `DATABASE_URL` environment variable should already be set for you.

Ideas for improvements
----------------------
- Add authentication/roles for admin controls.
- Add WebSockets to push updates instead of polling.
- Add better concurrency handling and background worker for automatic advancement.


# Vehicle Inventory Tracker

Multi-make vehicle inventory ingester and explorer. Pulls data from OEM APIs (Toyota GraphQL, Mazda REST), stores each make in a **separate MySQL database**, and provides a filterable web UI with pricing analytics.

## Features

### Explorer (`/`)

- **Multi-make support** — switch between Toyota and Mazda; each make uses an isolated database
- **Per-make filter memory** — series, models, dealers, states, colors, location, sort, and histogram selections persist in the browser when switching makes
- **Cascading filters** — series → model → color, drivetrain, stage, options, dealer, state, ZIP/radius
- **Pricing analytics** — histogram bins, MSRP comparison, geography map
- **Exports** — CSV (filtered inventory), PDF (vehicle detail and multi-vehicle reports)
- **Background job status** — ingest and sync progress visible in the main UI

### Admin (`/admin`)

- **Toyota** — sync model catalog, ingest by ZIP + radius (selected or all models)
- **Mazda** — nationwide dealer sync, dealer-ZIP vehicle refresh (1 mi per synced dealer ZIP), catalog ingest
- **Dealer geocoding** — batch geocode remaining dealers with cancel/progress
- **Job history** — ingest, catalog sync, dealer sync, dealer ZIP refresh, geocode runs with live progress

### Platform

- **Toyota ingest** from `api.search-inventory.toyota.com/graphql` with Playwright WAF auth
- **Mazda ingest** from `mazdausa.com` REST APIs with Playwright Akamai cookie bootstrap
- **MySQL storage** with run history, VIN lifecycle (active/inactive), compressed snapshots
- **Background jobs** via Redis + RQ worker (Docker) or in-process threads (local dev)

## Architecture

```
┌──────────────┐   Playwright    ┌──────────────────────┐
│ CLI / Admin  │ ──────────────► │ OEM sites (Toyota /  │
│ / Worker     │  auth cookies   │ Mazda inventory)     │
└──────┬───────┘                 └──────────────────────┘
       │
       │  Toyota: GraphQL getModels + LocateVehiclesByZip
       │  Mazda: dealer.ajax + inventorysearch (REST)
       ▼
┌─────────────────────────────┐     HTTP API      ┌──────────────┐
│ MySQL per make              │ ◄──────────────── │ Web :5050    │
│ (vehicle_inventory,        │                   │ Make switcher│
│  mazda_inventory)           │                   └──────────────┘
└─────────────────────────────┘
       ▲
       │
┌──────┴───────┐         Redis queue          ┌──────────────────┐
│ RQ Worker    │ ◄──────────────────────────► │ vit:{make}:job:* │
└──────────────┘                              └──────────────────┘
```

Each **make** uses its own MySQL database. Redis job keys are namespaced per make (`vit:toyota:job:live:ingest`, etc.).

## Quick start (Docker)

Recommended for full stack: MySQL, Redis, web, and background worker.

```bash
cp .env.example .env
# Edit .env: set MYSQL_* passwords, ADMIN_PASSWORD, FLASK_SECRET_KEY, etc.

docker compose up --build
```

Open:

- **Explorer:** [http://127.0.0.1:5050](http://127.0.0.1:5050)
- **Admin:** [http://127.0.0.1:5050/admin](http://127.0.0.1:5050/admin) (sign in with `ADMIN_PASSWORD`)
- **MySQL (Adminer):** [http://127.0.0.1:8080](http://127.0.0.1:8080) — System: **MySQL**, Server: **mysql**, credentials from `.env`
- **Redis (Redis Commander):** [http://127.0.0.1:8081](http://127.0.0.1:8081) — browse keys such as `vit:toyota:job:live:ingest`

Ports are overridable via `ADMINER_PORT` and `REDIS_COMMANDER_PORT` in `.env`.

### First-time ingest (admin)

1. Use the **Make** dropdown to select Toyota or Mazda
2. Sign in at `/admin`

**Toyota**

1. **Sync Model Catalog**
2. Select models (or **Refresh All Models**)
3. Set search ZIP + radius, then **Refresh Selected Models** or **Refresh All Models**

**Mazda**

1. **Sync Dealers (Nationwide)** — discovers dealers from seed ZIPs and stores them in `dealer_geo_cache` (required before dealer-ZIP refresh)
2. Optional: **Sync Model Catalog**, then pick models
3. Choose one ingest path:
   - **Refresh Selected (1 mi/ZIP)** / **Refresh All (1 mi/ZIP)** — queries each synced dealer ZIP at 1 mile radius (nationwide coverage, deduped by VIN)
   - **Refresh Selected Models** / **Refresh All Models** — classic ZIP + radius ingest (defaults: ZIP `95101`, 50 mi)

Playwright runs in the **worker** container to fetch session cookies when `USE_REDIS_JOBS=1` (Docker default).

### Data persistence

MySQL data is stored in a Docker **named volume** (`mysql_data`). It survives normal restarts:

```bash
docker compose down      # stops containers — data kept
docker compose up        # data still there
```

**Do not** use `docker compose down -v` unless you intend to wipe the database.

Browser filter state is stored in `localStorage` per make (`vit-filters:v1:{make}`) and survives page reloads.

## Local development (without Docker)

Requires a running MySQL 8 instance and `DATABASE_URL`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env
# Set DATABASE_URL=mysql+pymysql://vit:password@127.0.0.1:3306/vehicle_inventory

# Initialize schema (first run — primary make DB)
mysql -u ... -p vehicle_inventory < vehicle_inventory/db/schema_mysql.sql

# Mazda DB (optional)
mysql -u ... -e "CREATE DATABASE mazda_inventory CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u ... -p mazda_inventory < vehicle_inventory/db/schema_mysql.sql

export DATABASE_URL=mysql+pymysql://vit:password@127.0.0.1:3306/vehicle_inventory
python run_frontend.py --host 127.0.0.1 --port 5050
```

Optional: set `USE_REDIS_JOBS=1` and `REDIS_URL=redis://localhost:6379/0`, then run `python run_worker.py` in a second terminal.

### Tests

```bash
python run_tests.py
```

Unit tests run without a database. Integration tests run when `DATABASE_URL` points at MySQL.

### CLI entry points

| Script | Purpose |
|--------|---------|
| `run_frontend.py` | Web UI (FastAPI + uvicorn) |
| `run_worker.py` | RQ background worker |
| `run_ingest.py` | CLI ingest |
| `run_geocode_dealers.py` | CLI dealer geocoding |
| `run_tests.py` | Pytest suite |

## Environment variables

Copy `.env.example` to `.env`. Required and common variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | MySQL URL for the primary make DB, e.g. `mysql+pymysql://vit:pass@host:3306/vehicle_inventory` |
| `MAZDA_DATABASE_URL` | Optional | Mazda DB URL (defaults to `mazda_inventory` on same host) |
| `MAZDA_DATABASE` | Docker | Mazda database name (default `mazda_inventory`) |
| `DEFAULT_MAKE` | Optional | Default UI make: `toyota` or `mazda` |
| `MYSQL_ROOT_PASSWORD` | Docker | Root password for MySQL container |
| `MYSQL_DATABASE` | Docker | Primary database name (default `vehicle_inventory`) |
| `MYSQL_USER` / `MYSQL_PASSWORD` | Docker | App user credentials (default user `vit`) |
| `ADMIN_PASSWORD` | For `/admin` | Password for admin dashboard |
| `FLASK_SECRET_KEY` | Recommended | Session signing key |
| `REDIS_URL` | Docker jobs | e.g. `redis://redis:6379/0` |
| `USE_REDIS_JOBS` | Optional | `1` to queue ingest/geocode in worker |
| `TOYOTA_WAF_TOKEN` | Optional | Skip Playwright for Toyota ingest |
| `MAZDA_SESSION_COOKIE` | Optional | Skip Playwright for Mazda ingest |

## Project layout

```
vehicle-inventory-tracker/
├── vehicle_inventory/
│   ├── app.py                 # ASGI entry (FastAPI + Flask mount)
│   ├── core/                  # config, logging
│   ├── db/                    # MySQL layer, schema, run scope
│   ├── api/                   # web routes, filters, inventory, pricing
│   ├── ingest/                # shared progress + make router
│   ├── jobs/                  # RQ worker tasks, job history, service
│   ├── geo/                   # dealer geocoding
│   └── makes/                 # OEM adapters (extensibility point)
│       ├── base.py            # MakeAdapter protocol
│       ├── registry.py        # profiles + adapter lookup
│       ├── toyota/            # GraphQL client, WAF, ingest
│       └── mazda/             # REST client, session, ingest, dealers
├── templates/
├── static/                    # app.js, admin.js, vit-common.js
├── tests/
├── docker-compose.yml
└── run_*.py                   # CLI entry points
```

### Adding a new make

1. Create `vehicle_inventory/makes/<slug>/` with `client.py`, `ingest.py`, and `adapter.py` implementing `MakeAdapter`
2. Register the profile in `makes/registry.py` (`MakeProfile` + `_adapters()`)
3. Add a MySQL database (or shared DB strategy) and env var for `DATABASE_URL`
4. Optionally extend `image_host_suffixes()` for the image proxy

Schema: `vehicle_inventory/db/schema_mysql.sql` (applied automatically on first MySQL Docker startup for both `vehicle_inventory` and `mazda_inventory`).

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/makes` | List makes + current selection |
| POST | `/api/session/make` | Switch active make |
| GET | `/api/health` | Health check |
| GET | `/api/filters` | Cascading filter facets |
| GET | `/api/inventory` | Paginated inventory (scoped to current make) |
| GET | `/api/inventory/export` | CSV export for current filters |
| GET | `/api/inventory/analytics` | Pricing histogram + stats |
| GET | `/api/inventory/geo-map` | Geo map data |
| POST | `/api/catalog/sync` | Sync model catalog |
| POST | `/api/dealers/sync` | Nationwide dealer sync (Mazda) |
| POST | `/api/dealers/refresh-vehicles` | Dealer-ZIP vehicle refresh (Mazda) |
| POST | `/api/ingest/start` | Start background ingest |
| GET | `/api/ingest/status` | Ingest progress |
| GET | `/api/jobs/runs` | Job run history |
| GET | `/api/admin/overview` | Admin status (auth required) |

All data APIs accept `?make=toyota|mazda` or use session make from the UI switcher.

### Background job types

| Job type | Label | Description |
|----------|-------|-------------|
| `ingest` | Ingest | Model/ZIP inventory refresh |
| `catalog_sync` | Catalog sync | Toyota/Mazda model catalog |
| `dealer_sync` | Dealer sync | Mazda nationwide dealer discovery |
| `dealer_vehicle_refresh` | Dealer ZIP refresh | Mazda ingest at each synced dealer ZIP (1 mi) |
| `geocode` | Geocode | Batch dealer geocoding |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `DATABASE_URL is required` | Missing env | Set `DATABASE_URL` in `.env` |
| Mazda DB errors | DB not created | `CREATE DATABASE mazda_inventory;` or `docker compose down -v` + fresh init |
| HTTP 403 on Mazda ingest | Akamai cookies expired | Retry; set `MAZDA_SESSION_COOKIE` or ensure Playwright works in worker |
| Dealer ZIP refresh finds nothing | No dealers synced | Run **Sync Dealers (Nationwide)** first |
| Ingest queued but never runs | Worker not running | `docker compose ps`; restart worker |
| Stale RQ jobs after rename | Old task paths | Restart worker container |
| Filters reset on reload | Cached JS | Hard refresh after deploy (`app.js?v=…` cache bust in `index.html`) |

## Git push checklist

```bash
# First time only
git init
git add .
git commit -m "Initial commit: multi-make vehicle inventory tracker"

# Add your remote, then push
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

Ensure `.env` is never committed (listed in `.gitignore`). Copy `.env.example` on each machine.

## License

Private / personal use. OEM data is subject to each manufacturer's terms of service. Not affiliated with Toyota or Mazda.

# ChronoTrip AI

Multi-day itinerary optimiser (TOPTW) solved with a Memetic Genetic Algorithm, on place attributes learned from the
LBSN2Vec++ check-in dataset. Spec: `Dac_Ta_San_Pham_ChronoTrip_AI.docx`. UI: Figma "ChronoTrip AI – Product Design".

| Part | Stack | Folder |
| --- | --- | --- |
| Web | Next.js 16, MapLibre GL (OpenStreetMap), GSAP + ScrollTrigger + Lenis | `frontend/` |
| API | FastAPI, SQLAlchemy (SQLite locally, PostgreSQL/PostGIS in Docker) | `backend/app/` |
| Solver | Memetic GA-TOPTW, Numba kernel | `backend/solver/` |
| ML | Preprocessing, M1 LightGBM, M2 Dirichlet–Multinomial, M3 quantile GBM | `backend/ml/` |
| Routing | OSRM on the Geofabrik Vietnam extract (straight-line estimate if not running) | `scripts/prepare_osrm.sh` |

## Run locally (Windows / macOS / Linux)

One virtual environment at the repository root:

```bash
py -3.11 -m venv .venv                       # macOS/Linux: python3.11 -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/python
```

Build the data and models (first run downloads LBSN2Vec++, 2.68 GB, MD5-checked, resumable; then preprocesses
90M check-ins and trains M1–M3 — about 20 minutes in total):

```bash
.venv/Scripts/python -m app.bootstrap        # --skip-download to use files already in backend/data/raw
                                             # --sample for a 30-second synthetic run (no download)
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Web app (in another terminal):

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 — /api is proxied to http://127.0.0.1:8000 (BACKEND_URL)
```

Tests: `cd backend && ../.venv/Scripts/python -m pytest -q` (solver + API, uses the synthetic sample, no network).

Other entry points (run these from `backend/`): `python -m ml.download` (dataset only), `python -m ml.hours --raw data/raw` (crawl real opening hours from OpenStreetMap, optional, before training), `python -m ml.pipeline --raw data/raw` (retrain).

Model changes and the API contract for the frontend: [docs/model-changes.md](docs/model-changes.md), [docs/frontend-integration.md](docs/frontend-integration.md), and the Figma screen-by-screen API map: [docs/figma-api.md](docs/figma-api.md).
The admin screen (`/admin`) can also download the dataset, train a new version and activate it.

### Configuration (`backend/.env` or environment, prefix `CHRONOTRIP_`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHRONOTRIP_DATABASE_URL` | `sqlite:///backend/data/chronotrip.db` | e.g. `postgresql+psycopg://…` |
| `CHRONOTRIP_OSRM_URL` | empty | e.g. `http://localhost:5000`; empty = distance-based estimate |
| `CHRONOTRIP_ADMIN_TOKEN` | empty | protects `/api/admin/*` when set |
| `CHRONOTRIP_SOLVER_TIME_LIMIT_S` | `6` | GA time budget per request |

## Docker

```bash
sh scripts/prepare_osrm.sh          # once: builds ./osrm from the Vietnam OpenStreetMap extract
docker compose up --build           # web :3000, api :8000, PostGIS, OSRM
```

The first `api` start downloads the dataset into the `chronotrip-data` volume and trains the models.

## Results on the real dataset (version v1)

- 90,048,627 check-ins read, **18,281,127** kept in Southeast Asia (spec: 18,281,127); 804,580 candidate venues.
- 5,748 places in the app: 4,046 in Ho Chi Minh City, 1,702 in Hanoi.
- Test period Nov 2013 – Jan 2014, each model vs its baseline:
  - M1 Spearman 0.444 vs 0.197 raw count (Vietnam: 0.353 vs −0.048)
  - M2 log-likelihood −2.533 vs −2.727 category prior
  - M3 pinball loss 33.38 vs 34.11 category median

## Landing page motion

Lenis smooth scrolling + GSAP ScrollTrigger (pinned, scrubbed scenes), SplitText, DrawSVG and Flip:
hero depth parallax (scroll + pointer), Vietnam → HCMC → Thu Duc zoom, three-step "How it works" with the route
drawn along the scroll, horizontal rules track, data counter, GA chromosome. Planner screens keep native scrolling
so map zoom and drag-and-drop are never captured. `prefers-reduced-motion` turns all of it off and shows static
layouts; phones get shorter pins and no horizontal track.

## Data credit

LBSN2Vec++ — Dingqi Yang, Bingqing Qu, Jie Yang, Philippe Cudré-Mauroux, WWW'19 / IEEE TKDE 2020, CC BY 4.0,
DOI 10.4121/15112308.v1. Map data © OpenStreetMap contributors.

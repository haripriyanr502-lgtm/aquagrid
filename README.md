# AquaGrid — with DrainX road intelligence

AquaGrid is a stormwater-management and road-monitoring platform for Bengaluru. It joins:

- a **smart drain node** (Arduino) that measures water level and quality and sends clean water into a recharge pit,
- a **digital twin** (EPA SWMM + PySWMM) that forecasts flooding from Open-Meteo rain and chooses when to open recharge gates,
- **DrainX**, YOLOv8 pothole detection from images, videos, webcams and phone uploads,
- **road-risk** and **repair-priority** scoring with written explanations,
- **Telegram alerts**, and
- one **live React dashboard** with 10 sections.

Everything talks through one Supabase database. No service calls another directly.

> **Honesty labels used everywhere.** Virtual nodes are **SIMULATED**. The flood model is an **illustrative, uncalibrated** starter model. Node and segment coordinates are **approximate**. Pothole coordinates are only stored when they come from photo GPS, a GPS module, the phone/browser, or manual entry. Otherwise the record says *location unavailable*.

---

## Features

| Area | What it does | Where |
|---|---|---|
| Database | 8 original tables + migration 002 (history, repairs, upload queue, service health, storage bucket, RLS) | `database/` |
| Hardware bridge | USB serial ↔ Supabase, validated commands, auto-reconnect, hardware status, `--simulate` mode (labelled) | `scripts/bridge.py` |
| City simulator | 20 virtual nodes at flood-prone spots, storm/stop/reset commands | `scripts/simulator.py` |
| Digital twin | Open-Meteo rain, sensor correction, baseline / threshold / optimised scenarios, gate plan | `scripts/brain.py`, `twin/ward.inp` |
| DrainX AI | image, folder, video, webcam, dashboard uploads; boxes, confidence, severity, location, annotated images, alerts | `scripts/pothole_detect.py`, `scripts/drainx_ai.py` |
| Model evaluation | precision, recall, mAP50, mAP50-95, TP/FP/FN, confusion matrix | `scripts/evaluate_model.py` |
| Road risk | 0.6 × flood exposure + 0.4 × pothole density, history, HIGH/CRITICAL alerts | `scripts/road_risk.py`, `scripts/risk_model.py` |
| Repair priority | transparent ranking + reasons; status changed only by signed-in team members (logged) | `scripts/repair_priority.py` |
| Alerts | Telegram /start, /stop, severity, time, map link, sent once, duplicate prevention | `scripts/alerts.py` |
| Dashboard | Overview, Live Map, Flood, Digital Twin, DrainX, Road Risk, Repairs, Alerts, Control Room, System Health | `dashboard/` |
| Firmware | Arduino Uno smart node with quality gate | `firmware/drainx_node/` |

## Technology stack
Python 3.11 · Ultralytics YOLOv8 · OpenCV · PySWMM / EPA SWMM 5.2 · Open-Meteo · Supabase (Postgres, Realtime, Auth, Storage) · Telegram Bot API · React 19 + Vite · react-leaflet (OpenStreetMap) · Recharts · Arduino Uno.

No new frontend libraries were added. On the Python side only **Pillow** was added (to read GPS from photo EXIF).

## Folder structure
```
aquagrid/
├─ README.md                      this file
├─ docs/EXECUTION_GUIDE_WINDOWS.md  step-by-step for VS Code on Windows
├─ database/
│  ├─ 001_initial_schema.sql      original 8 tables (already applied in your project)
│  └─ 002_aquagrid_upgrade.sql    NEW - additive upgrade, safe to re-run
├─ firmware/drainx_node/drainx_node.ino
├─ twin/ward.inp                  SWMM starter model (illustrative)
├─ scripts/                       Python services
│  ├─ common.py  segments.py  risk_model.py  drainx_ai.py      shared modules
│  ├─ bridge.py  simulator.py  brain.py  alerts.py             services
│  ├─ road_risk.py  repair_priority.py  pothole_detect.py  evaluate_model.py
│  ├─ requirements.txt  requirements-ai.txt  .env.example  start_all.bat
│  └─ models/  (put best.pt here)
├─ dashboard/                     React + Vite app
│  └─ src/  App.jsx  supabase.js  lib/  components/  pages/ (10 sections)
└─ tests/                         offline test-suite + recorded results
```

## Installation
1. Install **Python 3.11**, **Node.js LTS**, **Git**, **VS Code** (and optionally EPA SWMM 5.2 for Windows).
2. Python, from the `scripts` folder:
   ```
   python -m venv .venv
   .venv\Scripts\activate            (Mac/Linux: source .venv/bin/activate)
   pip install -r requirements.txt
   pip install -r requirements-ai.txt   (only on the laptop that runs DrainX)
   ```
3. Dashboard, from the `dashboard` folder: `npm install`

## Configuration
- `scripts/.env` (copy from `.env.example`): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SERIAL_PORT`, `TELEGRAM_BOT_TOKEN` (or `BOT_TOKEN`), `POTHOLE_MODEL`, `POTHOLE_SEGMENT`, `POTHOLE_MIN_CONF`, `GPS_PORT`, `TWIN_LAT`, `TWIN_LNG`.
- `dashboard/.env` (copy from `.env.example`): `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (**anon key only**).
- Never commit `.env` files. They are in `.gitignore`.

## Database setup
1. If the project is new, run `database/001_initial_schema.sql` in the Supabase SQL Editor (your project already has it).
2. **Run `database/002_aquagrid_upgrade.sql`** once. It only adds columns, tables, policies, a trigger and the `detections` storage bucket. It flags old pothole rows whose coordinates were random as `legacy_random`.
3. Create team logins: Supabase → Authentication → Users → *Add user* (email + password). Signed-in users can upload detections, verify potholes and change repair status. Everyone else is read-only (plus control-room commands for the demo).

## Running the backend
Each service runs in its own terminal (or double-click `scripts\start_all.bat` on Windows):

| Command | Purpose |
|---|---|
| `python simulator.py` | start first: registers nodes, runs 20 virtual nodes |
| `python bridge.py` (or `python bridge.py --simulate`) | Arduino link (or labelled software model) |
| `python brain.py` | digital twin, forecast every 10 min, demo storms |
| `python alerts.py` | Telegram |
| `python road_risk.py` | risk every 30 s |
| `python repair_priority.py` | repair ranking every 60 s |
| `python pothole_detect.py --worker` | processes dashboard uploads |

## Frontend
```
cd dashboard
npm run dev        → http://localhost:5173
npm run build      → production files in dist/ (deploy dashboard/ on Vercel, root directory "dashboard")
```

## Simulator and digital twin
- Control Room → **Start Monsoon** sends `R:ON` to the real node, `STORM` to the simulator and `STORM` to the brain.
- The twin runs three scenarios on `twin/ward.inp` and stores flood volumes, flood curves, the gate plan, the rain source and an **assumptions** note in `runs`.
- Making the model real (elevations, drain sizes, calibration against a past flood) is described in the Software Build Guide, section 6.4. It has **not** been done yet.

## AI detection (DrainX)
1. Copy your trained weights to `scripts/models/best.pt` (not in Git; share via Drive).
2. Examples:
   ```
   python pothole_detect.py --source road.jpg
   python pothole_detect.py --source photos\ --segment J1
   python pothole_detect.py --source road.mp4 --no-show
   python pothole_detect.py --source 0                      (webcam)
   python pothole_detect.py --source road.jpg --lat 12.9177 --lng 77.6238   (only if you know the spot)
   python pothole_detect.py --source 0 --gps-port COM5      (USB GPS module)
   python pothole_detect.py --worker                        (dashboard uploads)
   ```
3. Measure real accuracy: `python evaluate_model.py --data <dataset folder>\data.yaml` (writes `models/metrics.json`, shown on the dashboard).
4. Default confidence threshold is **0.25**. The earlier 0.10 setting accepted very weak detections; the only recorded test so far was **19.22 % confidence**, so accuracy is still unproven.

## Hardware connection
Upload `firmware/drainx_node/drainx_node.ino` to the Uno (Hardware Guide). Close the Arduino Serial Monitor. Set `SERIAL_PORT` and run `python bridge.py`. Without hardware, use `python bridge.py --simulate`. Readings are then stored with `is_simulated = true` and shown as SIMULATED.

## Troubleshooting
| Problem | Fix |
|---|---|
| `Missing SUPABASE_URL` | create `scripts/.env` from `.env.example` |
| Dashboard says Supabase not configured | create `dashboard/.env`, restart `npm run dev` |
| "column … does not exist" / pages say run migration | run `database/002_aquagrid_upgrade.sql` |
| `Cannot open COM3` | wrong port or Serial Monitor open; or use `--simulate` |
| bridge: foreign key error | run `simulator.py` once to register SS-01 |
| Telegram silent | press START in the bot; only ONE `alerts.py` may run; check token |
| DrainX: model not found | put `best.pt` in `scripts/models/` or set `POTHOLE_MODEL` |
| Upload button disabled | sign in (team user created in Supabase Auth) |
| Upload stays "queued" | start `python pothole_detect.py --worker` |
| Road risk says "no flood forecast" | start `brain.py` and run a forecast; risk is not silently set to 0 |
| `pyswmm` install fails | use 64-bit Python 3.11 |

## Tests
`python tests/run_tests.py` runs 22 offline tests (risk maths, GPS/EXIF parsing, detector helpers, dedupe, services against an in-memory database, the twin optimiser against a fake SWMM engine). Results are recorded in `tests/*.json` and in the development report, including what was **not** tested.

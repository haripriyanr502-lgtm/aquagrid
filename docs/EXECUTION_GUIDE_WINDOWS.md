# AquaGrid — running everything in VS Code on Windows

Follow the parts in order. Text in `grey boxes` is typed exactly.

## Part A — one-time setup (about 30 minutes)

**A1. Install**
- Python **3.11** from python.org. On the first installer screen tick **“Add python.exe to PATH”**.
- Node.js **LTS** from nodejs.org.
- Git from git-scm.com, and VS Code from code.visualstudio.com.

**A2. Get the project**
1. Open VS Code → **File → Open Folder** → choose the unzipped `aquagrid` folder (the one with `README.md`).
2. **Terminal → New Terminal**. A PowerShell terminal opens at the bottom, already inside `aquagrid`.

**A3. Python environment** (in that terminal)
```
cd scripts
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-ai.txt
```
- The line now starts with `(.venv)`. You must activate the environment in **every new terminal**: `cd scripts` then `.venv\Scripts\activate`.
- If activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer `Y`, then try again.
- `requirements-ai.txt` is a large download (PyTorch). Only the laptop running DrainX needs it.

**A4. Secrets**
1. In VS Code's file list, right-click `scripts/.env.example` → Copy, then Paste, and rename the copy to `.env`.
2. Fill in `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role), `TELEGRAM_BOT_TOKEN` and `SERIAL_PORT` (Arduino IDE → Tools → Port, e.g. `COM3`).
3. Put the trained model at `scripts/models/best.pt`.

**A5. Database upgrade (once for the whole team)**
Supabase → SQL Editor → New query → paste all of `database/002_aquagrid_upgrade.sql` → **Run**.
Then go to Authentication → Users → **Add user** for each team member (email + password).

**A6. Dashboard**
Open a **second terminal** (click **+** in the terminal panel):
```
cd dashboard
npm install
```
Copy `dashboard/.env.example` to `dashboard/.env` and fill in `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (the **anon** key, never the service key).

## Part B — every time you run the demo

**Option 1 (easiest):** in File Explorer, open `aquagrid\scripts` and double-click **`start_all.bat`**. Seven windows open, one per service. Then do step B8.

**Option 2 (in VS Code):** open one terminal per service with **+**. In each one, first run:
```
cd scripts
.venv\Scripts\activate
```
then **one** of these commands per terminal, in this order:

| Terminal | Command | You should see |
|---|---|---|
| B1 | `python simulator.py` | `Registered 21 nodes`, then a line every 3 s |
| B2 | `python bridge.py` (no Arduino? `python bridge.py --simulate`) | `Connected to node on COM3` or `SIMULATED node` |
| B3 | `python brain.py` | a `[live_forecast]` line (needs internet) |
| B4 | `python alerts.py` | `Alert bot @… running` |
| B5 | `python road_risk.py` | 4 roads with labels every 30 s |
| B6 | `python repair_priority.py` | ranking every 60 s |
| B7 | `python pothole_detect.py --worker` | `Worker mode: waiting for uploads` |

**B8. Dashboard:** in the dashboard terminal run
```
npm run dev
```
Hold **Ctrl** and click `http://localhost:5173`. The badge at the top right must say **● LIVE**. Open **System Health**: every service should be green.

**Arduino:** close the Arduino IDE **Serial Monitor** before starting the bridge, because only one program can use the COM port.

## Part C — demo checklist
1. Control Room → **Start Monsoon**. Watch the Live Map, Flood Monitoring and Digital Twin pages.
2. Telegram: open your bot and press **START** before the demo. Alerts arrive within seconds.
3. DrainX → sign in → upload a road photo (or take one with the phone camera) → wait for the job to show **done**.
4. Road Risk and Repairs update within 30–60 s.
5. Stop: close each window, or press **Ctrl + C** in each terminal.

## Part D — checking AI accuracy (before the competition)
```
python evaluate_model.py --data C:\path\to\dataset\data.yaml
```
This writes `models\metrics.json`. The dashboard then shows precision, recall and mAP50. Quote only these measured numbers.

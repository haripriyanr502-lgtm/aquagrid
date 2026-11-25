"""
AquaGrid BRAIN - digital twin + forecast + optimiser
-----------------------------------------------------
1. Gets a rain forecast (Open-Meteo, free, no key) - or a demo storm.
2. Corrects it with what the real sensor is seeing right now (simple data assimilation).
3. Runs the SWMM digital twin (twin/ward.inp) three ways:
      baseline  = no recharge gates (what happens today)
      threshold = gates open when water crosses a fixed level (a normal "smart" sensor)
      optimised = AquaGrid: search for the best moment to open each gate so pit capacity
                  is saved for the flood PEAK instead of being wasted on early drizzle
4. Saves the result to `runs`, raises alerts, and steers the real node.

Run:  python brain.py
Commands it listens for (target 'BRAIN'):  STORM  (demo storm, time-compressed 1 s = 1 sim minute)
"""
import json
import os
import re
import time
from datetime import datetime

import requests

try:
    from pyswmm import Simulation, Nodes, Links
except ImportError:          # reported on the System Health page instead of crashing silently
    Simulation = Nodes = Links = None

from common import env, get_db, get_logger, heartbeat, mark_command, raise_alert, take_commands

log = get_logger("brain")
ASSUMPTIONS = ("ILLUSTRATIVE starter model of one corridor (twin/ward.inp). Pipe sizes, elevations and "
               "catchment areas are estimates, not survey data, and the model is NOT calibrated against "
               "real Bengaluru flood records. Volumes are simulation outputs.")

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_INP = os.path.join(HERE, "..", "twin", "ward.inp")
WORK_INP = os.path.join(HERE, "..", "twin", "_run.inp")

HOTSPOTS = ["J1", "J2", "J3", "J4"]
NAMES = {"J1": "HSR Layout", "J2": "Silk Board Jn", "J3": "BTM Layout", "J4": "Madiwala"}
GATES = {"OR1": "J2", "OR2": "J3"}          # gate -> junction it drains into a recharge pit
PITS = ["PIT1", "PIT2"]
REAL_NODE, REAL_JUNCTION = "SS-01", "J2"
THRESH_DEPTH_M = 0.45                        # what a simple threshold controller would use
LAT, LNG = float(env("TWIN_LAT", "12.9177")), float(env("TWIN_LNG", "77.6238"))
FORECAST_EVERY_S = 10 * 60
NEVER = 9999

# demo storm: mm/hr every 15 minutes (a heavy Bengaluru cloudburst, ~3 hours)
DEMO_STORM = [0, 5, 10, 20, 40, 70, 95, 70, 40, 20, 10, 5, 0]


# ----------------------------------------------------------------- rain
def forecast_rain():
    """Next 6 hours of rain intensity (mm/hr, 15-min steps) from Open-Meteo."""
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={LAT}&longitude={LNG}&minutely_15=precipitation"
           "&forecast_days=2&timezone=Asia%2FKolkata")
    data = requests.get(url, timeout=15).json()["minutely_15"]
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    start = next(i for i, t in enumerate(data["time"]) if t >= now)
    mm_per_15 = data["precipitation"][start:start + 24]
    return [round((v or 0) * 4, 2) for v in mm_per_15]       # mm per 15 min -> mm/hr


def sensor_correction(db, series):
    """If the real node sees water rising but the forecast says 'dry', trust the sensor."""
    try:
        res = (db.table("readings").select("level_pct,created_at,is_simulated").eq("node_id", REAL_NODE)
               .order("id", desc=True).limit(1).execute())
    except Exception:
        res = (db.table("readings").select("level_pct,created_at").eq("node_id", REAL_NODE)
               .order("id", desc=True).limit(1).execute())
    if not res.data or res.data[0].get("is_simulated"):
        return series, 1.0          # never correct a real forecast with simulated readings
    level = res.data[0]["level_pct"] or 0
    if level > 40 and sum(series[:4]) < 8:
        boost = round(level * 0.8, 1)                          # rough mm/hr estimate from level
        series = [max(v, boost) for v in series[:2]] + series[2:]
        log.info("Sensor correction: node at %s%% but forecast dry -> injecting %s mm/hr now", level, boost)
        return series, round(1 + level / 100, 2)
    return series, 1.0


# ----------------------------------------------------------------- twin
def write_inp(series):
    """Copy ward.inp with the rain series swapped in."""
    lines = ["[TIMESERIES]", ";;Name  Time  Value"]
    for i, v in enumerate(series):
        h, m = divmod(i * 15, 60)
        lines.append(f"RAIN  {h}:{m:02d}  {v:.2f}")
    h, m = divmod(len(series) * 15, 60)
    lines.append(f"RAIN  {h}:{m:02d}  0")
    with open(BASE_INP) as f:
        text = f.read()
    text = re.sub(r"\[TIMESERIES\].*?(?=\n\[)", lambda _: "\n".join(lines), text, flags=re.S)
    with open(WORK_INP, "w") as f:
        f.write(text)


def run_scenario(strategy, open_at=None):
    """Run the twin once. Returns flood volumes, timelines and water captured for recharge."""
    flood = {n: 0.0 for n in HOTSPOTS}
    first_flood = {n: None for n in HOTSPOTS}
    timeline = {n: [] for n in HOTSPOTS}
    with Simulation(WORK_INP) as sim:
        sim.step_advance(60)                                   # 1 simulated minute per loop
        nodes, links = Nodes(sim), Links(sim)
        junction = {n: nodes[n] for n in HOTSPOTS}
        gate = {g: links[g] for g in GATES}
        pit = {p: nodes[p] for p in PITS}
        opened = {g: False for g in GATES}
        start = last = sim.start_time
        for _ in sim:
            now = sim.current_time
            dt_s = (now - last).total_seconds()
            last = now
            minute = int((now - start).total_seconds() // 60)

            for g, n in GATES.items():
                if strategy == "baseline":
                    opened[g] = False
                elif strategy == "threshold":
                    opened[g] = opened[g] or junction[n].depth >= THRESH_DEPTH_M
                else:
                    opened[g] = minute >= open_at[g]
                gate[g].target_setting = 1.0 if opened[g] else 0.0

            for n in HOTSPOTS:
                q = junction[n].flooding                       # litres/second spilling onto the road
                flood[n] += q * dt_s / 1000.0                  # -> cubic metres
                if q > 1 and first_flood[n] is None:
                    first_flood[n] = minute
                if minute % 5 == 0 and (not timeline[n] or timeline[n][-1][0] != minute):
                    timeline[n].append([minute, round(junction[n].depth, 3), round(q, 1)])
        captured = sum(p.volume for p in pit.values())
    return {"flood": flood, "total": sum(flood.values()), "first_flood": first_flood,
            "timeline": timeline, "captured_m3": captured}


def optimise(baseline):
    """Coordinate search: for each gate try every opening minute, keep the best."""
    open_at = {g: NEVER for g in GATES}
    best = baseline
    for g, n in GATES.items():
        ff = baseline["first_flood"][n] or baseline["first_flood"][REAL_JUNCTION]
        if ff is None:
            continue
        candidates = sorted(set(list(range(max(0, ff - 90), ff + 31, 5)) + [NEVER]))
        for c in candidates:
            trial = dict(open_at, **{g: c})
            r = run_scenario("optimised", trial)
            if r["total"] < best["total"] - 0.01 or (abs(r["total"] - best["total"]) < 0.01
                                                    and r["captured_m3"] > best["captured_m3"]):
                best, open_at = r, trial
    return best, open_at


# ----------------------------------------------------------------- one planning cycle
def plan(db, series, scenario, factor=1.0, rain_source="unknown"):
    t0 = time.time()
    write_inp(series)
    base = run_scenario("baseline")
    thr = run_scenario("threshold")
    if base["total"] > 0.5:
        opt, open_at = optimise(base)
    else:                                                     # no flood expected -> just harvest water
        opt, open_at = thr, {g: NEVER for g in GATES}
    reduction = 0 if base["total"] < 0.5 else round(100 * (1 - opt["total"] / base["total"]), 1)

    risk = {n: {"name": NAMES[n], "floods_in_min": base["first_flood"][n],
                "flood_m3": round(base["flood"][n], 1), "flood_m3_optimised": round(opt["flood"][n], 1)}
            for n in HOTSPOTS}
    row = {
        "scenario": scenario,
        "rain_total_mm": round(sum(series) / 4, 1),
        "flood_m3_baseline": round(base["total"], 1),
        "flood_m3_threshold": round(thr["total"], 1),
        "flood_m3_optimised": round(opt["total"], 1),
        "reduction_pct": reduction,
        "captured_m3": round(opt["captured_m3"], 1),
        "sensor_factor": factor,
        "details": {"open_at": open_at, "risk": risk, "rain": series, "rain_source": rain_source,
                    "assumptions": ASSUMPTIONS, "gates": GATES, "threshold_depth_m": THRESH_DEPTH_M,
                    "speed": 60 if scenario == "demo_storm" else 1,
                    "timeline": {"baseline": base["timeline"], "threshold": thr["timeline"],
                                 "optimised": opt["timeline"]}},
    }
    db.table("runs").insert(json.loads(json.dumps(row))).execute()
    log.info("[%s] flood baseline %.0f m3 | threshold %.0f | optimised %.0f (-%s%%) plan %s in %.1fs",
             scenario, base['total'], thr['total'], opt['total'], reduction, open_at, time.time() - t0)

    ff = base["first_flood"][REAL_JUNCTION]
    if ff is not None:
        sim = " (demo storm, simulated)" if scenario == "demo_storm" else ""
        raise_alert(db, "flood_forecast",
                    f"Flood predicted at {NAMES[REAL_JUNCTION]} in {ff} min{sim}. AquaGrid is reserving pit "
                    f"capacity - modelled flooding cut by {reduction}%.", REAL_NODE, severity="warning",
                    dedupe_key=f"flood:{scenario}:{int(time.time() // 300)}", segment=REAL_JUNCTION)
    return open_at, ff


def send(db, *commands):
    db.table("commands").insert([{"node_id": REAL_NODE, "command": c} for c in commands]).execute()


def steer_real_node(db, open_at, ff, speed):
    """Turn the plan into commands for the physical node.
    Before the planned moment: high threshold (keep pit capacity in reserve).
    At the planned moment:     low threshold (release capacity for the peak)."""
    if ff is None:
        send(db, "D:AUTO", "T:60")
        return None
    send(db, "D:AUTO", "T:85")
    m = open_at.get("OR1", NEVER)
    if m == NEVER:
        return None
    return time.time() + m * 60 / speed                       # wall-clock time to release


def main():
    db = get_db()
    next_forecast = 0
    release_at = None
    storm_end = None
    last_beat, last_ok = 0.0, None
    while True:
        for c in take_commands(db, "BRAIN"):
            if c["command"].strip().upper() == "STORM":
                log.info("Demo storm received - planning...")
                if Simulation is None:
                    mark_command(db, c["id"], "failed", "pyswmm not installed")
                    continue
                open_at, ff = plan(db, DEMO_STORM, "demo_storm", rain_source="demo design storm")
                mark_command(db, c["id"], "done", f"twin run complete, release at minute {open_at.get('OR1')}")
                release_at = steer_real_node(db, open_at, ff, speed=60)
                storm_end = time.time() + len(DEMO_STORM) * 15 + 30
                next_forecast = storm_end + FORECAST_EVERY_S

        if release_at and time.time() >= release_at:
            send(db, "T:25")
            raise_alert(db, "gate", f"Releasing recharge gate at {NAMES[REAL_JUNCTION]} now - "
                        "flood peak arriving.", REAL_NODE, severity="info",
                        dedupe_key=f"gate:{int(time.time() // 120)}", segment=REAL_JUNCTION)
            release_at = None
        if storm_end and time.time() >= storm_end:
            send(db, "T:60")
            storm_end = None

        if time.time() >= next_forecast:
            next_forecast = time.time() + FORECAST_EVERY_S
            if Simulation is None:
                log.error("pyswmm is not installed - pip install -r requirements.txt")
                heartbeat(db, "brain", "error", error="pyswmm not installed")
            else:
                try:
                    series, factor = sensor_correction(db, forecast_rain())
                    open_at, ff = plan(db, series, "live_forecast", factor, rain_source="Open-Meteo forecast")
                    release_at = steer_real_node(db, open_at, ff, speed=1) or release_at
                    last_ok = time.time()
                except Exception as e:
                    log.warning("forecast cycle failed: %s", e)
                    heartbeat(db, "brain", "warning", error=f"forecast failed: {str(e)[:150]}")
        if time.time() - last_beat >= 10 and Simulation is not None:
            last_beat = time.time()
            heartbeat(db, "brain", "ok", pyswmm=True, release_pending=bool(release_at),
                      next_forecast_in_s=max(0, int(next_forecast - time.time())), last_forecast_ok=last_ok)
        time.sleep(1)


if __name__ == "__main__":
    main()

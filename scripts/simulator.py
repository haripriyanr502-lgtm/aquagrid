"""
AquaGrid city simulator: 20 virtual nodes at flood-prone Bengaluru locations.
  * registers all nodes (real + virtual) in the `nodes` table
  * every 3 s writes one realistic reading per virtual node
  * listens for commands to target 'SIM':  STORM (start a 3-minute monsoon), STOP, RESET
Coordinates are APPROXIMATE - verify each one on Google Maps before the demo.
Every row is written with is_simulated = true and the dashboard labels these nodes SIMULATED.
They are not real installations.
Run:  python simulator.py
"""
import math
import random
import time

from common import get_db, get_logger, heartbeat, take_commands, raise_alert

log = get_logger("simulator")

TICK_S = 3
STORM_S = 180          # demo storm lasts 3 minutes (same compression as brain.py: 1 s = 1 sim minute)

# id, name, lat, lng, swmm junction (if part of the twin), sensitivity (how badly it floods)
NODES = [
    ("SS-01", "Silk Board Jn (REAL NODE)", 12.9177, 77.6238, "J2", 1.0),
    ("SV-01", "HSR Layout 27th Main",      12.9121, 77.6446, "J1", 0.8),
    ("SV-02", "BTM Layout 2nd Stage",      12.9166, 77.6101, "J3", 1.1),
    ("SV-03", "Madiwala",                  12.9226, 77.6174, "J4", 0.9),
    ("SV-04", "Bellandur",                 12.9260, 77.6762, None, 1.3),
    ("SV-05", "Sarjapur Rd - Rainbow Dr",  12.9056, 77.6850, None, 1.4),
    ("SV-06", "Hebbal Flyover",            13.0358, 77.5970, None, 1.0),
    ("SV-07", "KR Puram",                  13.0076, 77.6950, None, 1.0),
    ("SV-08", "Mahadevapura",              12.9915, 77.6890, None, 1.1),
    ("SV-09", "Koramangala 6th Block",     12.9352, 77.6245, None, 1.2),
    ("SV-10", "Marathahalli Bridge",       12.9569, 77.7011, None, 1.0),
    ("SV-11", "Yelahanka",                 13.1007, 77.5963, None, 0.8),
    ("SV-12", "Shantinagar",               12.9580, 77.5990, None, 1.0),
    ("SV-13", "Okalipuram Underpass",      12.9800, 77.5650, None, 1.3),
    ("SV-14", "Nayandahalli",              12.9440, 77.5250, None, 0.9),
    ("SV-15", "Bommanahalli",              12.9000, 77.6230, None, 1.1),
    ("SV-16", "Domlur",                    12.9610, 77.6387, None, 0.9),
    ("SV-17", "Ejipura",                   12.9430, 77.6280, None, 1.2),
    ("SV-18", "Whitefield",                12.9698, 77.7500, None, 0.8),
    ("SV-19", "Kasturi Nagar",             13.0050, 77.6620, None, 0.9),
    ("SV-20", "Banashankari",              12.9255, 77.5468, None, 0.7),
]
POLLUTED = {"SV-13"}   # this node always gets dirty runoff -> shows the quality gate rejecting water
SIM_FLOW_LPM = 900     # a real-scale recharge pit intake (litres/min) - virtual nodes are city scale


def register_nodes(db):
    rows = [{"id": i, "name": n, "lat": la, "lng": lo, "kind": "real" if i.startswith("SS") else "virtual",
             "swmm_node": s} for i, n, la, lo, s, _ in NODES]
    db.table("nodes").upsert(rows).execute()
    log.info("Registered %d nodes", len(rows))


def storm_intensity(t):
    """0..1 bell curve: builds up, peaks at 45 % of the storm, fades."""
    if t is None or t < 0 or t > STORM_S:
        return 0.0
    x = t / STORM_S
    return math.exp(-((x - 0.45) ** 2) / 0.03)


def main():
    db = get_db()
    register_nodes(db)
    state = {i: {"level": random.uniform(3, 8), "pit": random.uniform(5, 15), "litres": 0.0, "gate": False}
             for i, *_ in NODES if i != "SS-01"}
    storm_start = None

    while True:
        for c in take_commands(db, "SIM"):
            cmd = c["command"].strip().upper()
            if cmd == "STORM":
                storm_start = time.time()
                log.info("Monsoon started (simulated)")
            elif cmd == "STOP":
                storm_start = None
                log.info("Monsoon stopped")
            elif cmd == "RESET":
                for s in state.values():
                    s.update(level=5, pit=10, litres=0.0, gate=False)
                log.info("Reset")

        t = (time.time() - storm_start) if storm_start else None
        if t is not None and t > STORM_S + 60:
            storm_start, t = None, None
        rain = storm_intensity(t)

        rows = []
        for nid, name, lat, lng, swmm, sens in NODES:
            if nid == "SS-01":
                continue
            s = state[nid]
            target = min(100, 6 + 95 * rain * sens)
            s["level"] += (target - s["level"]) * 0.25 + random.uniform(-1.2, 1.2)
            first_flush = t is not None and t < 25
            quality_ok = (nid not in POLLUTED) and not first_flush and s["level"] > 20

            want = s["level"] >= 60 or (s["gate"] and s["level"] > 50)
            if want and not quality_ok:
                reason = "first_flush_to_drain" if first_flush else "dirty_water_to_drain"
                want = False
            elif want and s["pit"] >= 85:
                reason, want = "pit_full", False
            else:
                reason = "open" if want else "below_threshold"
            s["gate"] = want

            flow = SIM_FLOW_LPM * random.uniform(0.85, 1.15) if want else 0.0
            if want:
                s["level"] -= 4
                s["pit"] += 2.0
                s["litres"] += flow * TICK_S / 60
            s["pit"] = max(0, s["pit"] - 0.4)          # slow seepage into the ground
            s["level"] = max(0, min(100, s["level"]))

            rows.append({
                "node_id": nid, "level_pct": round(s["level"], 1), "pit_pct": round(s["pit"], 1),
                "turbidity": random.randint(250, 450) if not quality_ok and s["level"] > 20 else random.randint(650, 800),
                "tds": random.randint(700, 950) if nid in POLLUTED else random.randint(180, 420),
                "soil_pct": round(min(100, 30 + s["pit"] * 0.7), 0),
                "flow_lpm": round(flow, 1), "litres_total": round(s["litres"], 1),
                "gate_open": want, "rain_on": rain > 0.05, "quality_ok": quality_ok,
                "first_flush": first_flush, "mode": "AUTO", "reason": reason, "threshold": 60,
                "is_simulated": True,
            })
        try:
            db.table("readings").insert(rows).execute()
        except Exception as e:
            if "is_simulated" in str(e):
                raise SystemExit("Run database/002_aquagrid_upgrade.sql first (simulated readings must be labelled).")
            log.warning("upload failed: %s", e)

        if t is not None and abs(t - 60) < TICK_S / 2:
            raise_alert(db, "quality", "Polluted runoff at Okalipuram Underpass (SIMULATED node) - "
                        "rejected from recharge pit.", "SV-13", severity="warning",
                        dedupe_key=f"sim-quality:{int(storm_start)}")
        flooding = sum(1 for s in state.values() if s["level"] > 85)
        total_l = sum(s['litres'] for s in state.values())
        log.info("rain %.2f  nodes >85%%: %2d  network litres %s", rain, flooding, f"{total_l:,.0f}")
        heartbeat(db, "simulator", "ok", virtual_nodes=len(state), storm_active=storm_start is not None,
                  rain_intensity=round(rain, 2), flooding_nodes=flooding)
        time.sleep(TICK_S)


if __name__ == "__main__":
    main()

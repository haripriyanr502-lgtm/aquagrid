"""
AquaGrid road-risk service
  risk = 0.6 x flood exposure (digital twin)  +  0.4 x pothole density (DrainX, last 30 days)
Reads the latest twin run and pothole records, writes `road_risk` (current) and
`road_risk_history` (trend), and raises a deduplicated alert when a road turns HIGH/CRITICAL.
Run:  python road_risk.py            (loop every 30 s)
      python road_risk.py --once     (single calculation, prints the table)
"""
import sys
import time
from datetime import datetime, timedelta, timezone

from common import get_db, get_logger, heartbeat, now_iso, raise_alert
from risk_model import road_risk
from segments import SEGMENTS

log = get_logger("road_risk")
FORECAST_MAX_AGE_H = 24          # older twin runs are treated as "no forecast"
HISTORY_EVERY_S = 600


def latest_flood(db):
    """Per-segment predicted flood volume (m3) from the newest twin run, or None per segment."""
    since = (datetime.now(timezone.utc) - timedelta(hours=FORECAST_MAX_AGE_H)).isoformat()
    run = (db.table("runs").select("id,scenario,details,created_at").gte("created_at", since)
           .order("id", desc=True).limit(1).execute().data)
    if not run:
        return {}, None
    risk = (run[0].get("details") or {}).get("risk") or {}
    return {seg: risk[seg].get("flood_m3") for seg in risk}, run[0]


def recent_potholes(db):
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        return (db.table("potholes").select("road_segment,severity,verification,created_at")
                .gte("created_at", since).execute().data or [])
    except Exception:   # before migration 002 (no severity / verification columns)
        return (db.table("potholes").select("road_segment,created_at")
                .gte("created_at", since).execute().data or [])


def compute(db):
    flood, run = latest_flood(db)
    potholes = recent_potholes(db)
    rows = []
    for seg, info in SEGMENTS.items():
        r = road_risk(flood.get(seg), [p for p in potholes if p.get("road_segment") == seg])
        rows.append({"segment": seg, "name": info["name"], "lat": info["lat"], "lng": info["lng"],
                     **r, "updated_at": now_iso()})
    return rows, run


def main():
    db = get_db()
    once = "--once" in sys.argv
    last_history, last_label = 0.0, {}
    while True:
        try:
            rows, run = compute(db)
            try:
                db.table("road_risk").upsert(rows).execute()
            except Exception as e:
                if "column" not in str(e):
                    raise
                legacy = [{k: v for k, v in r.items() if k not in ("flood_available", "severity_score",
                           "explanation")} | {"flood_score": r["flood_score"] or 0} for r in rows]
                db.table("road_risk").upsert(legacy).execute()
                log.warning("Run database/002_aquagrid_upgrade.sql to store explanations and history")

            changed = any(last_label.get(r["segment"]) != r["label"] for r in rows)
            if changed or time.time() - last_history >= HISTORY_EVERY_S:
                try:
                    db.table("road_risk_history").insert([
                        {k: r[k] for k in ("segment", "risk", "label", "flood_score", "pothole_score",
                                           "pothole_count", "flood_available")} for r in rows]).execute()
                    last_history = time.time()
                except Exception:
                    pass

            for r in rows:
                if r["label"] in ("HIGH", "CRITICAL") and last_label.get(r["segment"]) != r["label"]:
                    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    raise_alert(db, "road_risk",
                                f"{r['name']} is now {r['label']} risk (score {r['risk']:.2f}). {r['explanation']}",
                                severity="critical" if r["label"] == "CRITICAL" else "warning",
                                dedupe_key=f"risk:{r['segment']}:{r['label']}:{day}",
                                lat=r["lat"], lng=r["lng"], segment=r["segment"])
                last_label[r["segment"]] = r["label"]

            src = f"twin run #{run['id']} ({run['scenario']})" if run else "NO flood forecast in last 24 h"
            log.info("%s | %s", src, " | ".join(f"{r['name']}: {r['label']} {r['risk']:.2f}" for r in rows))
            heartbeat(db, "road_risk", "ok" if run else "warning",
                      flood_source=src, segments=len(rows))
        except Exception as e:
            log.error("risk update failed: %s", e)
            heartbeat(db, "road_risk", "error", error=str(e)[:200])
        if once:
            break
        time.sleep(30)


if __name__ == "__main__":
    main()

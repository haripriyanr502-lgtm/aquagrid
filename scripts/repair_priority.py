"""
AquaGrid repair-priority service
Ranks road segments for maintenance and explains every ranking.
  priority = 55 % road risk + 20 % high-severity share + 15 % repeat detections + 10 % team-confirmed
Scores and reasons are recalculated every 60 s. The repair STATUS is never changed here:
only a signed-in team member can change it from the dashboard (Repair Management page).
Run:  python repair_priority.py           (loop)
      python repair_priority.py --once
"""
import sys
import time
from datetime import datetime, timedelta, timezone

from common import get_db, get_logger, heartbeat, now_iso
from risk_model import repair_priority
from segments import SEGMENTS

log = get_logger("repair_priority")


def compute(db):
    risk_rows = {r["segment"]: r for r in (db.table("road_risk").select("*").execute().data or [])}
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    try:
        pots = (db.table("potholes").select("road_segment,severity,verification,created_at")
                .gte("created_at", since).execute().data or [])
    except Exception:
        pots = (db.table("potholes").select("road_segment,created_at")
                .gte("created_at", since).execute().data or [])
    out = []
    for seg, info in SEGMENTS.items():
        risk = risk_rows.get(seg, {"risk": 0.0, "label": "UNKNOWN", "flood_available": False})
        p = repair_priority(risk, [x for x in pots if x.get("road_segment") == seg])
        out.append({"segment": seg, "name": info["name"], "lat": info["lat"], "lng": info["lng"],
                    **p, "computed_at": now_iso()})
    out.sort(key=lambda r: r["priority_score"], reverse=True)
    for i, r in enumerate(out, 1):
        r["priority_rank"] = i
    return out


def main():
    db = get_db()
    once = "--once" in sys.argv
    while True:
        try:
            rows = compute(db)
            db.table("repair_tickets").upsert(rows, on_conflict="segment").execute()   # status untouched
            log.info(" | ".join(f"#{r['priority_rank']} {r['name']} {r['priority_score']} {r['urgency']}"
                                for r in rows))
            heartbeat(db, "repair_priority", "ok", segments=len(rows))
        except Exception as e:
            log.error("priority update failed: %s", e)
            heartbeat(db, "repair_priority", "error", error=str(e)[:200])
        if once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()

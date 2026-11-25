"""
AquaGrid road-risk and repair-priority model (pure functions, no database).

Risk  = 0.6 x flood exposure + 0.4 x pothole density          (Software Build Guide)
Labels: LOW < 0.20 <= MEDIUM < 0.45 <= HIGH < 0.70 <= CRITICAL

Normalisation (documented starting values - tune with real repair records):
  flood exposure  = predicted flood volume at the segment / FLOOD_M3_FOR_MAX   (capped at 1)
  pothole density = severity-weighted count of confirmed/unverified potholes
                    in the last 30 days / POTHOLES_FOR_MAX                     (capped at 1)
False-positive potholes are excluded. When no flood forecast exists the flood term is
UNKNOWN (not zero): the score is computed from potholes only and flagged.
"""
from datetime import datetime, timezone

W_FLOOD, W_POTHOLE = 0.6, 0.4
FLOOD_M3_FOR_MAX = 300.0
POTHOLES_FOR_MAX = 10.0
SEVERITY_WEIGHT = {"HIGH": 1.5, "MEDIUM": 1.0, "LOW": 0.6, None: 1.0}
LABELS = [(0.70, "CRITICAL"), (0.45, "HIGH"), (0.20, "MEDIUM"), (0.0, "LOW")]
REPAIR_STATUSES = ["Reported", "Under Review", "Repair Scheduled", "In Progress", "Completed"]


def label(score):
    if score is None:
        return "UNKNOWN"
    for limit, name in LABELS:
        if score >= limit:
            return name
    return "LOW"


def severity_from_area(area_pct):
    """Heuristic: share of the frame covered by the largest pothole box."""
    if area_pct is None:
        return None
    if area_pct >= 15:
        return "HIGH"
    if area_pct >= 5:
        return "MEDIUM"
    return "LOW"


def usable_potholes(potholes):
    return [p for p in potholes if p.get("verification") != "false_positive"]


def pothole_density(potholes):
    """Severity-weighted pothole load -> 0..1"""
    load = sum(SEVERITY_WEIGHT.get(p.get("severity"), 1.0) for p in usable_potholes(potholes))
    return min(1.0, load / POTHOLES_FOR_MAX), load


def flood_exposure(flood_m3):
    """None means 'no forecast available' and stays None."""
    if flood_m3 is None:
        return None
    return min(1.0, max(0.0, float(flood_m3)) / FLOOD_M3_FOR_MAX)


def road_risk(flood_m3, potholes):
    """Returns dict with score, label, components and a plain-English explanation."""
    pot, load = pothole_density(potholes)
    flood = flood_exposure(flood_m3)
    n = len(usable_potholes(potholes))
    if flood is None:
        score = round(W_POTHOLE * pot, 3)
        note = ("No flood forecast available yet - score uses potholes only and may be "
                "UNDER-estimated. Run brain.py to add flood exposure.")
    else:
        score = round(W_FLOOD * flood + W_POTHOLE * pot, 3)
        note = (f"Flood exposure {flood:.2f} (predicted {flood_m3:.0f} m3 of road flooding) x 0.6 + "
                f"pothole density {pot:.2f} ({n} potholes, weighted load {load:.1f}) x 0.4")
    return {
        "risk": score, "label": label(score),
        "flood_score": None if flood is None else round(flood, 3),
        "pothole_score": round(pot, 3), "pothole_count": n,
        "severity_score": round(load, 2), "flood_available": flood is not None,
        "explanation": note,
    }


def _days_since(iso):
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400
    except Exception:
        return None


def repair_priority(segment_risk, potholes):
    """
    Priority score (0-100), transparent:
      55 % road risk score
      20 % share of HIGH-severity potholes
      15 % repeat detections (same segment flagged in 3+ separate days)
      10 % confirmed by a person (verification = confirmed)
    """
    pts = usable_potholes(potholes)
    n = len(pts)
    high = sum(1 for p in pts if p.get("severity") == "HIGH")
    confirmed = sum(1 for p in pts if p.get("verification") == "confirmed")
    days = {str(p.get("created_at", ""))[:10] for p in pts if p.get("created_at")}
    risk = segment_risk.get("risk") or 0.0

    f_risk = risk
    f_high = (high / n) if n else 0.0
    f_repeat = min(1.0, len(days) / 3.0)
    f_confirm = (confirmed / n) if n else 0.0
    score = round(100 * (0.55 * f_risk + 0.20 * f_high + 0.15 * f_repeat + 0.10 * f_confirm), 1)

    reasons = [f"Road risk {risk:.2f} ({segment_risk.get('label', 'UNKNOWN')})"]
    if not segment_risk.get("flood_available"):
        reasons.append("Flood forecast missing - risk may be under-estimated")
    elif (segment_risk.get("flood_score") or 0) >= 0.5:
        reasons.append("Predicted to flood heavily in the current forecast")
    if n:
        reasons.append(f"{n} pothole detection(s), {high} high-severity")
    else:
        reasons.append("No pothole detections yet")
    if len(days) >= 2:
        reasons.append(f"Detected on {len(days)} different days (repeat problem)")
    if confirmed:
        reasons.append(f"{confirmed} confirmed by the team")

    if score >= 70:
        urgency = "IMMEDIATE"
    elif score >= 50:
        urgency = "HIGH"
    elif score >= 30:
        urgency = "MEDIUM"
    elif n:
        urgency = "LOW"
    else:
        urgency = "MONITOR"
    factors = {"risk": round(f_risk, 3), "high_severity_share": round(f_high, 3),
               "repeat_days": len(days), "confirmed_share": round(f_confirm, 3), "detections": n}
    return {"priority_score": score, "urgency": urgency, "reasons": reasons, "factors": factors}

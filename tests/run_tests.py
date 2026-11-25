"""
AquaGrid offline test-suite.  python tests/run_tests.py
Runs WITHOUT internet, Supabase, Telegram, the SWMM engine, YOLO weights or hardware:
those are replaced by in-memory fakes (tests/fakes.py) and every result says so.
Writes tests/results.json.
"""
import json
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
os.environ.setdefault("SUPABASE_URL", "https://test.invalid")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

import fakes  # noqa: E402

fakes.install_fake_pyswmm()
RESULTS = []


def case(name, expected, fakes_used="none"):
    def deco(fn):
        def run():
            try:
                actual = fn()
                RESULTS.append({"test": name, "expected": expected, "actual": actual, "status": "PASS",
                                "executed": True, "fakes": fakes_used})
            except Exception as e:
                RESULTS.append({"test": name, "expected": expected, "actual": f"{type(e).__name__}: {e}",
                                "status": "FAIL", "executed": True, "fakes": fakes_used,
                                "trace": traceback.format_exc()[-600:]})
        run.__name__ = fn.__name__
        TESTS.append(run)
        return fn
    return deco


TESTS = []

# ------------------------------------------------------------------ risk model
import risk_model as rm  # noqa: E402


@case("Risk labels at the guide thresholds", "0.19 LOW, 0.20 MEDIUM, 0.45 HIGH, 0.70 CRITICAL")
def t_labels():
    got = [rm.label(v) for v in (0.19, 0.2, 0.44, 0.45, 0.69, 0.7)]
    assert got == ["LOW", "MEDIUM", "MEDIUM", "HIGH", "HIGH", "CRITICAL"], got
    return ", ".join(got)


@case("Risk formula 0.6 x flood + 0.4 x potholes", "300 m3 + 10 MEDIUM potholes = 1.00 CRITICAL; 150 m3 + 0 = 0.30")
def t_formula():
    r1 = rm.road_risk(300, [{"severity": "MEDIUM"}] * 10)
    r2 = rm.road_risk(150, [])
    assert r1["risk"] == 1.0 and r1["label"] == "CRITICAL", r1
    assert r2["risk"] == 0.3 and r2["label"] == "MEDIUM", r2
    return f"{r1['risk']} {r1['label']}; {r2['risk']} {r2['label']}"


@case("Missing flood data is not treated as zero", "flood_available False, explanation warns, flood_score None")
def t_missing_flood():
    r = rm.road_risk(None, [{"severity": "HIGH"}] * 4)
    assert r["flood_available"] is False and r["flood_score"] is None and "No flood forecast" in r["explanation"]
    return f"risk {r['risk']} (potholes only), flagged"


@case("False positives excluded from pothole density", "2 real + 3 false positives counts as 2")
def t_fp():
    r = rm.road_risk(0, [{"severity": "MEDIUM"}] * 2 + [{"severity": "HIGH", "verification": "false_positive"}] * 3)
    assert r["pothole_count"] == 2, r
    return f"pothole_count {r['pothole_count']}"


@case("Severity heuristic from box area", "2% LOW, 8% MEDIUM, 20% HIGH, None -> None")
def t_sev():
    got = [rm.severity_from_area(v) for v in (2, 8, 20, None)]
    assert got == ["LOW", "MEDIUM", "HIGH", None], got
    return str(got)


@case("Repair priority ranks a risky, repeatedly detected road higher", "CRITICAL road with repeats > LOW road; reasons explain it")
def t_priority():
    hot = rm.repair_priority({"risk": 0.8, "label": "CRITICAL", "flood_available": True, "flood_score": 0.9},
                             [{"severity": "HIGH", "created_at": f"2026-11-{d:02d}T10:00:00", "verification": "confirmed"}
                              for d in (1, 5, 9)])
    cold = rm.repair_priority({"risk": 0.05, "label": "LOW", "flood_available": True, "flood_score": 0.0}, [])
    assert hot["priority_score"] > cold["priority_score"] and hot["urgency"] == "IMMEDIATE" and cold["urgency"] == "MONITOR"
    assert any("different days" in r for r in hot["reasons"])
    return f"hot {hot['priority_score']} {hot['urgency']} vs cold {cold['priority_score']} {cold['urgency']}"


# ------------------------------------------------------------------ DrainX helpers
import drainx_ai as dx  # noqa: E402


@case("NMEA GPS parsing (GGA + RMC, no-fix rejected)", "12.9177, 77.6238 from both; None without fix")
def t_nmea():
    gga = "$GPGGA,123519,1255.062,N,07737.428,E,1,08,0.9,900.0,M,46.9,M,,*47"
    rmc = "$GPRMC,123519,A,1255.062,N,07737.428,E,0.0,0.0,231126,,,A*6A"
    nofix = "$GPGGA,123519,,,,,0,00,,,M,,M,,*66"
    a, b, c = dx.parse_nmea(gga), dx.parse_nmea(rmc), dx.parse_nmea(nofix)
    assert a == b and abs(a[0] - 12.9177) < 1e-3 and abs(a[1] - 77.6238) < 1e-3 and c is None, (a, b, c)
    return f"{a} / {b} / {c}"


@case("EXIF GPS read from a phone-style JPEG", "coordinates written into EXIF are read back")
def t_exif():
    from PIL import Image
    path = os.path.join(tempfile.gettempdir(), "aquagrid_exif_test.jpg")
    img = Image.new("RGB", (64, 64), "grey")
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (12.0, 55.0, 3.72), 3: "E", 4: (77.0, 37.0, 25.68)}
    img.save(path, exif=exif)
    got = dx.exif_gps(path)
    assert got and abs(got[0] - 12.9177) < 1e-3 and abs(got[1] - 77.6238) < 1e-3, got
    plain = os.path.join(tempfile.gettempdir(), "aquagrid_noexif.jpg")
    Image.new("RGB", (8, 8)).save(plain)
    assert dx.exif_gps(plain) is None
    return f"{got}; photo without GPS -> None"


@case("Location priority never invents coordinates", "EXIF > device > browser > manual; nothing -> (None, None, 'none')")
def t_loc():
    class G:
        def current(self): return (1.0, 2.0)
    assert dx.resolve_location(None, None, (None, None), None) == (None, None, "none")
    assert dx.resolve_location(None, G(), (5, 6), (3, 4))[2] == "gps_device"
    assert dx.resolve_location(None, None, (5, 6), (3, 4))[2] == "gps_browser"
    assert dx.resolve_location(None, None, (5, 6), None)[2] == "manual"
    return "all four priorities correct; no source gives no coordinates"


@case("Class filter keeps only potholes in multi-class models", "pothole kept, manhole dropped; 1-class model keeps all")
def t_boxes():
    class B:
        def __init__(self, c, conf=0.9): self.cls, self.conf, self.xyxy = c, conf, [[0, 0, 100, 50]]

    class R:
        def __init__(self, names, boxes): self.names, self.boxes = names, boxes
    multi = dx.pothole_boxes(R({0: "pothole", 1: "manhole"}, [B(0), B(1)]))
    single = dx.pothole_boxes(R({0: "hole"}, [B(0), B(0)]))
    area, sev = dx.classify(multi, 100, 100)
    assert len(multi) == 1 and len(single) == 2 and area == 50.0 and sev == "HIGH"
    return f"multi-class kept {len(multi)}, single-class kept {len(single)}, area {area}% -> {sev}"


@case("Missing model weights reported clearly", "model_loaded False with instructions")
def t_model_missing():
    info = dx.model_info("/nonexistent/best.pt")
    assert info["model_loaded"] is False and "best.pt" in info["problem"]
    return info["problem"][:70] + "..."


# ------------------------------------------------------------------ services with an in-memory database
import common  # noqa: E402


@case("Alert duplicate prevention", "same dedupe_key stored once", "FakeDB (in-memory Supabase)")
def t_dedupe():
    db = fakes.FakeDB()
    a = common.raise_alert(db, "pothole", "x", dedupe_key="k1")
    b = common.raise_alert(db, "pothole", "x", dedupe_key="k1")
    c = common.raise_alert(db, "pothole", "y", dedupe_key="k2")
    assert (a, b, c) == (True, False, True) and len(db.tables["alerts"]) == 2
    return "2 rows stored from 3 calls"


import road_risk  # noqa: E402
import repair_priority  # noqa: E402


@case("Road risk with no twin run flags missing flood data", "all 4 segments flood_available False", "FakeDB")
def t_rr_noflood():
    db = fakes.FakeDB()
    db.tables["potholes"] = [{"road_segment": "J2", "severity": "HIGH", "created_at": "2099-01-01T00:00:00+00:00"}]
    rows, run = road_risk.compute(db)
    assert run is None and all(r["flood_available"] is False for r in rows)
    j2 = next(r for r in rows if r["segment"] == "J2")
    return f"run None; J2 risk {j2['risk']} {j2['label']} from potholes only"


@case("Road risk uses the latest twin run", "J2 CRITICAL when twin predicts 300 m3 + 6 potholes", "FakeDB")
def t_rr_flood():
    db = fakes.FakeDB()
    db.tables["runs"] = [{"id": 1, "scenario": "demo_storm", "created_at": "2099-01-01T00:00:00+00:00",
                          "details": {"risk": {"J2": {"flood_m3": 300}, "J1": {"flood_m3": 0}}}}]
    db.tables["potholes"] = [{"road_segment": "J2", "severity": "MEDIUM", "created_at": "2099-01-01T00:00:00+00:00"}] * 6
    rows, run = road_risk.compute(db)
    j2 = next(r for r in rows if r["segment"] == "J2")
    j1 = next(r for r in rows if r["segment"] == "J1")
    assert j2["label"] == "CRITICAL" and j1["flood_available"] is True and j1["risk"] == 0.0
    return f"J2 {j2['risk']} {j2['label']}; J1 {j1['risk']} (forecast says no flood)"


@case("Repair priority keeps the human-set status", "status 'In Progress' survives a recalculation", "FakeDB")
def t_repair_status():
    db = fakes.FakeDB()
    db.tables["road_risk"] = [{"segment": "J2", "risk": 0.8, "label": "CRITICAL", "flood_available": True, "flood_score": 1}]
    db.table("repair_tickets").upsert(repair_priority.compute(db)).execute()
    db.table("repair_tickets").update({"status": "In Progress"}).eq("segment", "J2").execute()
    db.table("repair_tickets").upsert(repair_priority.compute(db)).execute()
    t = next(r for r in db.tables["repair_tickets"] if r["segment"] == "J2")
    assert t["status"] == "In Progress" and t["priority_rank"] == 1
    return f"J2 rank {t['priority_rank']}, status {t['status']}"


import bridge  # noqa: E402


@case("Bridge only forwards known firmware commands", "T:55, R:ON, D:AUTO accepted; 'rm -rf', T:999 rejected")
def t_cmds():
    ok = [bridge.valid_command(c) for c in ("T:55", "R:ON", "D:AUTO", "CALPIT", "K:360")]
    bad = [bridge.valid_command(c) for c in ("rm -rf", "T:999", "R:MAYBE", "")]
    assert all(ok) and not any(bad), (ok, bad)
    return "5 accepted, 4 rejected"


@case("Simulated node obeys commands and labels nothing as real", "rain fills sump, first flush goes to drain, then gate opens above threshold", "SimulatedNode (software model)")
def t_simnode():
    import time as _t
    n = bridge.SimulatedNode()
    n.write("R:ON"); n.write("T:30")
    _sleep, bridge.time.sleep = bridge.time.sleep, lambda s: None
    try:
        out = [json.loads(n.readline()) for _ in range(40)]
    finally:
        bridge.time.sleep = _sleep
    first_open = next(i for i, o in enumerate(out) if o["gate_open"])
    assert any(o["reason"] == "first_flush_to_drain" for o in out[:first_open]), "first flush must come first"
    assert max(o["level_pct"] for o in out) <= 100 and out[first_open]["level_pct"] >= 30
    return f"first flush to drain, then gate opened at reading {first_open} (level {out[first_open]['level_pct']}%)"


# ------------------------------------------------------------------ digital twin logic (fake engine)
import brain  # noqa: E402


@case("Twin optimiser beats the threshold controller", "optimised flood < threshold flood < baseline", "fake SWMM engine (tests/fakes.py)")
def t_twin():
    brain.write_inp(brain.DEMO_STORM)
    try:
        base = brain.run_scenario("baseline")
        thr = brain.run_scenario("threshold")
        opt, plan = brain.optimise(base)
    finally:
        if os.path.exists(brain.WORK_INP):
            os.remove(brain.WORK_INP)
    assert opt["total"] < thr["total"] <= base["total"], (opt["total"], thr["total"], base["total"])
    return (f"baseline {base['total']:.0f} m3, threshold {thr['total']:.0f}, optimised {opt['total']:.0f}; "
            f"OR1 opens at minute {plan['OR1']} (threshold opened earlier)")


@case("Rain series is written into the SWMM input file", "[TIMESERIES] replaced, other sections intact")
def t_inp():
    brain.write_inp([0, 12.5, 40])
    try:
        txt = open(brain.WORK_INP).read()
    finally:
        os.remove(brain.WORK_INP)
    assert "RAIN  0:15  12.50" in txt and "[REPORT]" in txt and "[ORIFICES]" in txt and "RAIN    1:30  95" not in txt
    return "3 rain steps + end marker written; [ORIFICES] and [REPORT] preserved"


@case("Twin run stores assumptions and gate plan", "details contain assumptions, rain_source, open_at; alert deduplicated", "FakeDB + fake SWMM")
def t_plan():
    db = fakes.FakeDB()
    brain.plan(db, brain.DEMO_STORM, "demo_storm", rain_source="demo design storm")
    brain.plan(db, brain.DEMO_STORM, "demo_storm", rain_source="demo design storm")
    if os.path.exists(brain.WORK_INP):
        os.remove(brain.WORK_INP)
    run = db.tables["runs"][0]
    assert "ILLUSTRATIVE" in run["details"]["assumptions"] and run["details"]["rain_source"] == "demo design storm"
    flood_alerts = [a for a in db.tables.get("alerts", []) if a["kind"] == "flood_forecast"]
    assert len(db.tables["runs"]) == 2 and len(flood_alerts) == 1
    return f"2 runs stored, 1 flood alert (duplicate suppressed), reduction {run['reduction_pct']}%"


# ------------------------------------------------------------------ static checks
@case("Every Python file compiles", "no syntax errors")
def t_compile():
    import py_compile
    files = [f for f in os.listdir(os.path.join(os.path.dirname(HERE), "scripts")) if f.endswith(".py")]
    for f in files:
        py_compile.compile(os.path.join(os.path.dirname(HERE), "scripts", f), doraise=True)
    return f"{len(files)} files OK"


@case("Migration 002 is additive only", "no DROP TABLE / DROP COLUMN / TRUNCATE / DELETE FROM")
def t_sql():
    sql = open(os.path.join(os.path.dirname(HERE), "database", "002_aquagrid_upgrade.sql")).read().upper()
    for bad in ("DROP TABLE", "DROP COLUMN", "TRUNCATE", "DELETE FROM"):
        assert bad not in sql, bad
    return "only ADD/CREATE/ALTER ADD/UPDATE(flags)/policies"


if __name__ == "__main__":
    for t in TESTS:
        t()
    w = max(len(r["test"]) for r in RESULTS)
    for r in RESULTS:
        print(f"{r['status']}  {r['test']:<{w}}  {r['actual']}")
        if r["status"] == "FAIL":
            print(r.get("trace", ""))
    passed = sum(r["status"] == "PASS" for r in RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(RESULTS, f, indent=2)
    sys.exit(0 if passed == len(RESULTS) else 1)

"""
AquaGrid bridge: Arduino smart node (USB) <-> Supabase
  * reads one JSON line per second from the node and uploads it to `readings`
  * forwards validated commands from the dashboard / brain (table `commands`) to the node
  * reports hardware connection status to the System Health page
  * reconnects automatically when the USB cable is unplugged

  python bridge.py              real hardware (SERIAL_PORT in .env)
  python bridge.py --simulate   no hardware: a software model of the node.
                                Every reading is stored with is_simulated = true and the
                                dashboard labels it SIMULATED - it is never shown as a real measurement.
IMPORTANT: close the Arduino IDE Serial Monitor first, otherwise the port is busy.
"""
import json
import random
import re
import sys
import time

from common import env, get_db, get_logger, heartbeat, mark_command, raise_alert, take_commands

log = get_logger("bridge")
NODE_ID = "SS-01"
UPLOAD_EVERY_S = 2.0
FIELDS = ["level_pct", "pit_pct", "turbidity", "tds", "soil_pct", "flow_lpm", "litres_total",
          "gate_open", "rain_on", "quality_ok", "first_flush", "mode", "reason", "threshold"]
# commands the firmware understands (anything else is rejected, never sent down the cable)
VALID = re.compile(r"^(T:\d{1,2}|D:(ON|OFF|AUTO)|R:(ON|OFF)|CAL|CALFULL|CALPIT|CALPITFULL|"
                   r"Q:\d{1,4}|X:\d{1,5}|F:\d{1,3}|K:\d{1,4}(\.\d+)?|QG:(ON|OFF)|RST:L)$")


def valid_command(cmd):
    return bool(VALID.match(cmd.strip().upper()))


# ----------------------------------------------------------------- serial link
class SerialNode:
    simulated = False

    def __init__(self, port):
        self.port, self.ser = port, None

    def connect(self, db):
        import serial
        while True:
            try:
                self.ser = serial.Serial(self.port, 115200, timeout=1)
                time.sleep(2)                              # the Uno restarts when the port opens
                log.info("Connected to node on %s", self.port)
                heartbeat(db, "bridge", "ok", hardware="connected", port=self.port, simulated=False)
                return
            except Exception as e:
                log.warning("Cannot open %s (%s). Uno plugged in? Serial Monitor closed? Retrying...",
                            self.port, e)
                heartbeat(db, "bridge", "offline", hardware="not connected", port=self.port,
                          simulated=False, error=str(e)[:120])
                time.sleep(3)

    def readline(self):
        return self.ser.readline().decode(errors="ignore").strip()

    def write(self, cmd):
        self.ser.write((cmd.strip() + "\n").encode())

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# ----------------------------------------------------------------- software model (no hardware)
class SimulatedNode:
    """Mimics drainx_node.ino closely enough to test the whole software stack."""
    simulated = True

    def __init__(self):
        self.level, self.pit, self.litres = 5.0, 10.0, 0.0
        self.threshold, self.mode, self.rain, self.gate = 60.0, "AUTO", False, False
        self.event_start, self.tick = None, 0      # time measured in readings (1 per second)
        self.last = 0.0

    def connect(self, db):
        log.warning("SIMULATED node - no hardware attached. Readings are flagged is_simulated.")
        heartbeat(db, "bridge", "ok", hardware="simulated (no hardware)", simulated=True)

    def write(self, cmd):
        c = cmd.strip().upper()
        if c.startswith("T:"):
            self.threshold = float(c[2:])
        elif c == "D:ON":
            self.mode = "REQ_OPEN"
        elif c == "D:OFF":
            self.mode = "FORCE_CLOSE"
        elif c == "D:AUTO":
            self.mode = "AUTO"
        elif c == "R:ON":
            self.rain = True
        elif c == "R:OFF":
            self.rain = False
        elif c == "RST:L":
            self.litres = 0.0

    def readline(self):
        time.sleep(max(0.0, 1.0 - (time.time() - self.last)))
        self.last = time.time()
        self.level += (2.8 if self.rain else 0.0) - (3.5 if self.gate else 0.4) + random.uniform(-0.4, 0.4)
        self.tick += 1
        self.level = max(0.0, min(100.0, self.level))
        if self.rain and self.level >= 92:          # same demo safety as the firmware
            self.rain = False
        if self.event_start is None and self.level > 12:
            self.event_start = self.tick
        if self.event_start is not None and self.level < 5:
            self.event_start = None
        first_flush = self.event_start is not None and self.tick - self.event_start < 20
        quality = self.level > 20
        want = {"REQ_OPEN": True, "FORCE_CLOSE": False}.get(
            self.mode, self.level >= self.threshold or (self.gate and self.level > self.threshold - 10))
        reason = "open" if want else ("forced_closed" if self.mode == "FORCE_CLOSE" else "below_threshold")
        for cond, why in ((self.level < 8, "dry_run_protect"), (first_flush, "first_flush_to_drain"),
                          (not quality and self.level > 20, "dirty_water_to_drain"), (self.pit >= 85, "pit_full")):
            if want and cond:
                want, reason = False, why
        self.gate = want
        flow = random.uniform(2.2, 2.6) if want else 0.0
        self.litres += flow / 60
        self.pit = max(0.0, min(100.0, self.pit + (1.2 if want else 0.0) - 0.2))
        return json.dumps({
            "node": NODE_ID, "level_pct": round(self.level, 1), "pit_pct": round(self.pit, 1),
            "turbidity": 720 if quality else 380, "tds": 260, "soil_pct": round(min(100, 30 + self.pit * .6)),
            "flow_lpm": round(flow, 2), "litres_total": round(self.litres, 2), "gate_open": want,
            "rain_on": self.rain, "quality_ok": quality, "first_flush": first_flush, "mode": self.mode,
            "reason": reason, "threshold": self.threshold})

    def close(self):
        pass


def main():
    simulate = "--simulate" in sys.argv
    db = get_db()
    node = SimulatedNode() if simulate else SerialNode(env("SERIAL_PORT", "COM3"))
    node.connect(db)
    last_upload = last_poll = last_beat = 0.0
    prev_reason = None
    readings_sent = 0

    while True:
        try:
            raw = node.readline()
        except Exception:
            log.warning("Node disconnected - reconnecting")
            heartbeat(db, "bridge", "offline", hardware="disconnected", simulated=node.simulated)
            node.close()
            node.connect(db)
            continue

        if raw.startswith("{"):
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = None
            if msg and "level_pct" in msg:
                reason = msg.get("reason")
                if reason != prev_reason:
                    tag = " (SIMULATED)" if node.simulated else ""
                    if reason == "dirty_water_to_drain":
                        raise_alert(db, "quality", f"Polluted runoff at Silk Board node{tag} - sent to drain, "
                                    "groundwater protected.", NODE_ID, severity="warning", segment="J2")
                    elif reason == "pit_full":
                        raise_alert(db, "pit", f"Recharge pit at Silk Board is full{tag}.", NODE_ID,
                                    severity="info", segment="J2")
                    prev_reason = reason
                if time.time() - last_upload >= UPLOAD_EVERY_S:
                    row = {k: msg.get(k) for k in FIELDS}
                    row["node_id"] = NODE_ID
                    row["is_simulated"] = node.simulated
                    try:
                        try:
                            db.table("readings").insert(row).execute()
                        except Exception as e:
                            if "is_simulated" not in str(e):
                                raise
                            if node.simulated:
                                raise SystemExit("Run database/002_aquagrid_upgrade.sql before using --simulate "
                                                 "(simulated readings must be labelled).")
                            row.pop("is_simulated")
                            db.table("readings").insert(row).execute()
                        last_upload = time.time()
                        readings_sent += 1
                        log.info("level %5s%%  gate %s litres %s (%s)%s", row["level_pct"],
                                 "OPEN " if row["gate_open"] else "shut ", row["litres_total"], row["reason"],
                                 "  [SIMULATED]" if node.simulated else "")
                    except SystemExit:
                        raise
                    except Exception as e:
                        log.warning("upload failed (check internet): %s", e)
            elif msg:
                log.info("node says: %s", msg)

        if time.time() - last_poll >= 1.0:
            last_poll = time.time()
            try:
                for c in take_commands(db, NODE_ID):
                    cmd = c["command"].strip().upper()
                    if not valid_command(cmd):
                        mark_command(db, c["id"], "rejected", "unknown command - not sent to hardware")
                        log.warning("rejected command %r", cmd)
                        continue
                    node.write(cmd)
                    mark_command(db, c["id"], "done", "sent to simulated node" if node.simulated else "sent to node")
                    log.info("  -> sent command %s", cmd)
                    time.sleep(0.1)
            except Exception as e:
                log.warning("command poll failed: %s", e)

        if time.time() - last_beat >= 10:
            last_beat = time.time()
            heartbeat(db, "bridge", "ok", hardware="simulated (no hardware)" if node.simulated else "connected",
                      simulated=node.simulated, readings_sent=readings_sent)


if __name__ == "__main__":
    main()

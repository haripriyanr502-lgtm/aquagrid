"""Shared helpers for every AquaGrid laptop service: config, logging, database, alerts, heartbeats."""
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
load_dotenv(os.path.join(HERE, ".env"))          # scripts/.env (never committed)

_DB = None


# ----------------------------------------------------------------- config
def env(name, default=None, required=True):
    value = os.environ.get(name, default)
    if value is None and required:
        raise SystemExit(f"Missing {name} in scripts/.env - copy .env.example to .env and fill it in.")
    return value


def env_any(names, default=None, required=True):
    """First variable that is set, e.g. env_any(['TELEGRAM_BOT_TOKEN', 'BOT_TOKEN'])."""
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    if default is None and required:
        raise SystemExit(f"Missing one of {', '.join(names)} in scripts/.env")
    return default


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        raise SystemExit(f"{name} must be a number")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------- logging
def get_logger(name):
    log = logging.getLogger(name)
    if not log.handlers:
        os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
        fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%H:%M:%S")
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        filelog = logging.FileHandler(os.path.join(HERE, "logs", f"{name}.log"), encoding="utf-8")
        filelog.setFormatter(fmt)
        log.addHandler(console)
        log.addHandler(filelog)
        log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    return log


# ----------------------------------------------------------------- database
def get_db():
    """Supabase client using the SERVICE ROLE key (laptop only - never in the dashboard)."""
    global _DB
    if _DB is None:
        from supabase import create_client
        _DB = create_client(env("SUPABASE_URL"), env("SUPABASE_SERVICE_KEY"))
    return _DB


def take_commands(db, target):
    """Fetch pending commands for one target ('SS-01', 'SIM', 'BRAIN') and mark them done."""
    res = (db.table("commands").select("*")
           .eq("node_id", target).eq("status", "pending")
           .order("id").execute())
    cmds = res.data or []
    for c in cmds:
        db.table("commands").update({"status": "done", "sent_at": now_iso()}).eq("id", c["id"]).execute()
    return cmds


def mark_command(db, command_id, status, result=None):
    try:
        db.table("commands").update({"status": status, "result": result}).eq("id", command_id).execute()
    except Exception:
        pass


def raise_alert(db, kind, message, node_id=None, severity="info", dedupe_key=None,
                lat=None, lng=None, segment=None):
    """Write one alert. The dashboard shows it live and alerts.py pushes it to Telegram.
    dedupe_key: the same key is only ever stored once (duplicate prevention)."""
    row = {"kind": kind, "message": message, "node_id": node_id, "severity": severity,
           "dedupe_key": dedupe_key, "lat": lat, "lng": lng, "segment": segment}
    try:
        db.table("alerts").insert(row).execute()
        get_logger("alerts").info("[%s/%s] %s", kind, severity, message.replace("\n", " | "))
        return True
    except Exception as e:
        text = str(e)
        if "duplicate key" in text or "23505" in text:
            return False                         # already alerted - not an error
        if "column" in text and ("severity" in text or "dedupe_key" in text):
            # database not migrated yet (002) - fall back to the original columns
            db.table("alerts").insert({"kind": kind, "message": message, "node_id": node_id}).execute()
            return True
        get_logger("alerts").warning("alert failed: %s", e)
        return False


def heartbeat(db, service, status="ok", **detail):
    """Tell the System Health page this service is alive."""
    try:
        db.table("service_status").upsert({"service": service, "status": status,
                                           "detail": detail, "last_seen": now_iso()}).execute()
    except Exception:
        pass   # health reporting must never stop a service

"""
AquaGrid alerts -> Telegram
  * /start subscribes a chat, /stop unsubscribes (judges scan the bot QR code)
  * every new alert row (pothole, flood forecast, road risk, pollution, gate, pit) is pushed
    to all subscribers with severity, time and location
  * each alert is sent once: rows are marked sent_telegram = true (survives restarts)
Token: TELEGRAM_BOT_TOKEN (or BOT_TOKEN, the name used in the first version)
Run:  python alerts.py
"""
import time
from datetime import datetime, timedelta, timezone

import requests

from common import env_any, get_db, get_logger, heartbeat

log = get_logger("alerts")
TOKEN = env_any(["TELEGRAM_BOT_TOKEN", "BOT_TOKEN"])
API = f"https://api.telegram.org/bot{TOKEN}"
ICONS = {"flood_forecast": "🌧️", "quality": "🧪", "gate": "🚰", "pit": "🟦", "pothole": "🕳️",
         "road_risk": "🛣️"}
SEV = {"critical": "🔴 CRITICAL", "warning": "🟠 WARNING", "info": "🔵 INFO"}
RESEND_WINDOW_MIN = 15        # after a restart, unsent alerts newer than this are still delivered


def tg(method, **params):
    return requests.post(f"{API}/{method}", json=params, timeout=30).json()


def format_alert(a):
    lines = [f"{ICONS.get(a.get('kind'), '⚠️')} AquaGrid · {SEV.get(a.get('severity') or 'info', '🔵 INFO')}",
             a["message"]]
    if a.get("lat") is not None and a.get("lng") is not None:
        lines.append(f"📍 https://maps.google.com/?q={a['lat']:.5f},{a['lng']:.5f}")
    try:
        t = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00")) + timedelta(hours=5, minutes=30)
        lines.append(f"🕒 {t:%d %b %Y, %H:%M} IST")
    except Exception:
        pass
    return "\n".join(lines)


def pending_alerts(db, state):
    if state["migrated"]:
        since = (datetime.now(timezone.utc) - timedelta(minutes=RESEND_WINDOW_MIN)).isoformat()
        try:
            return (db.table("alerts").select("*").eq("sent_telegram", False)
                    .gte("created_at", since).order("id").execute().data or [])
        except Exception:
            state["migrated"] = False
            log.warning("alerts table not upgraded - run database/002_aquagrid_upgrade.sql")
    return (db.table("alerts").select("*").gt("id", state["last_id"]).order("id").execute().data or [])


def main():
    db = get_db()
    last = db.table("alerts").select("id").order("id", desc=True).limit(1).execute().data
    state = {"migrated": True, "last_id": last[0]["id"] if last else 0}
    me = tg("getMe")
    if not me.get("ok"):
        heartbeat(db, "alerts", "error", error="Telegram token rejected")
        raise SystemExit(f"Telegram rejected the token: {me}")
    bot = me["result"]["username"]
    log.info("Alert bot @%s running. Open t.me/%s and press START.", bot, bot)
    offset, sent_total, last_error = 0, 0, None

    while True:
        # 1. subscriptions
        try:
            for u in tg("getUpdates", offset=offset, timeout=2).get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                text, chat = msg.get("text", ""), msg.get("chat", {})
                if text.startswith("/start"):
                    db.table("subscribers").upsert({"chat_id": chat["id"],
                                                    "name": chat.get("first_name", "")}).execute()
                    tg("sendMessage", chat_id=chat["id"],
                       text="✅ Subscribed to AquaGrid live alerts (Bengaluru).\n"
                            "Flood forecasts, potholes, road risk and water-quality events.\nSend /stop to leave.")
                    log.info("New subscriber: %s", chat.get("first_name"))
                elif text.startswith("/stop"):
                    db.table("subscribers").delete().eq("chat_id", chat["id"]).execute()
                    tg("sendMessage", chat_id=chat["id"], text="You will no longer receive AquaGrid alerts.")
        except Exception as e:
            last_error = f"poll: {e}"
            log.warning("telegram poll failed: %s", e)

        # 2. delivery
        try:
            new = pending_alerts(db, state)
            if new:
                subs = db.table("subscribers").select("chat_id").execute().data or []
                for a in new:
                    text = format_alert(a)
                    for s in subs:
                        r = tg("sendMessage", chat_id=s["chat_id"], text=text, disable_web_page_preview=True)
                        if not r.get("ok"):
                            log.warning("send to %s failed: %s", s["chat_id"], r.get("description"))
                    if state["migrated"]:
                        db.table("alerts").update({"sent_telegram": True}).eq("id", a["id"]).execute()
                    state["last_id"] = a["id"]
                    sent_total += 1
                    log.info("pushed to %d: %s", len(subs), a["message"].replace("\n", " | "))
            subs_n = len(db.table("subscribers").select("chat_id").execute().data or [])
            heartbeat(db, "alerts", "ok" if not last_error else "warning", bot=f"@{bot}",
                      subscribers=subs_n, sent_this_session=sent_total, last_error=last_error)
            last_error = None
        except Exception as e:
            log.warning("alert push failed: %s", e)
            heartbeat(db, "alerts", "error", error=str(e)[:200])
        time.sleep(1)


if __name__ == "__main__":
    main()

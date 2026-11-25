"""
DrainX helper functions: location (EXIF / GPS hardware / manual), pothole filtering,
severity and model information. No database access here, so it can be unit-tested.
"""
import os
import threading
import time

from risk_model import severity_from_area


# ----------------------------------------------------------------- model
def model_info(path):
    if not os.path.exists(path):
        return {"model_loaded": False, "model_path": path,
                "problem": f"Model weights not found at {path}. Copy your trained best.pt there "
                           "(see README > AI pothole detection)."}
    st = os.stat(path)
    return {"model_loaded": True, "model_path": path, "size_mb": round(st.st_size / 1e6, 1),
            "model_version": f"{os.path.basename(path)}@{time.strftime('%Y-%m-%d', time.localtime(st.st_mtime))}"}


def pothole_boxes(result):
    """Boxes whose class name contains 'pothole' (works for 1-class and multi-class datasets)."""
    if result.boxes is None or len(result.boxes) == 0:
        return []
    names = getattr(result, "names", {}) or {}
    out = []
    for b in result.boxes:
        cls = int(b.cls)
        name = str(names.get(cls, "pothole")).lower()
        if "pothole" in name or len(names) <= 1:
            out.append(b)
    return out


def largest_area_pct(boxes, img_h, img_w):
    if not boxes or not img_h or not img_w:
        return None
    best = 0.0
    for b in boxes:
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        best = max(best, max(0.0, x2 - x1) * max(0.0, y2 - y1))
    return round(100.0 * best / (img_h * img_w), 2)


def classify(boxes, img_h, img_w):
    area = largest_area_pct(boxes, img_h, img_w)
    return area, severity_from_area(area)


# ----------------------------------------------------------------- EXIF GPS
def _to_deg(dms, ref):
    d, m, s = [float(x) for x in dms]
    deg = d + m / 60.0 + s / 3600.0
    return -deg if ref in ("S", "W") else deg


def exif_gps(path):
    """(lat, lng) from a photo's EXIF GPS block, or None. Phones add this when location is on."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            gps = im.getexif().get_ifd(0x8825)
        if not gps or 2 not in gps or 4 not in gps:
            return None
        lat = _to_deg(gps[2], gps.get(1, "N"))
        lng = _to_deg(gps[4], gps.get(3, "E"))
        if abs(lat) < 1e-6 and abs(lng) < 1e-6:
            return None
        return round(lat, 6), round(lng, 6)
    except Exception:
        return None


# ----------------------------------------------------------------- GPS hardware (NMEA)
def _nmea_coord(value, hemi):
    if not value:
        return None
    dot = value.index(".")
    deg = float(value[:dot - 2])
    minutes = float(value[dot - 2:])
    c = deg + minutes / 60.0
    return -c if hemi in ("S", "W") else c


def parse_nmea(line):
    """Parse $GPGGA/$GNGGA or $GPRMC/$GNRMC. Returns (lat, lng) only when the receiver has a fix."""
    try:
        line = line.strip()
        if not line.startswith("$"):
            return None
        body = line[1:].split("*")[0]
        f = body.split(",")
        kind = f[0][2:]
        if kind == "GGA" and len(f) > 6 and f[6] not in ("", "0"):
            lat, lng = _nmea_coord(f[2], f[3]), _nmea_coord(f[4], f[5])
        elif kind == "RMC" and len(f) > 6 and f[2] == "A":
            lat, lng = _nmea_coord(f[3], f[4]), _nmea_coord(f[5], f[6])
        else:
            return None
        if lat is None or lng is None:
            return None
        return round(lat, 6), round(lng, 6)
    except (ValueError, IndexError):
        return None


class GpsReader:
    """Reads a USB/serial GPS module (e.g. NEO-6M via USB-TTL) in the background."""

    def __init__(self, port, baud=9600, max_age_s=5):
        import serial
        self.ser = serial.Serial(port, baud, timeout=1)
        self.max_age_s = max_age_s
        self.fix, self.fix_time = None, 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                fix = parse_nmea(self.ser.readline().decode(errors="ignore"))
                if fix:
                    self.fix, self.fix_time = fix, time.time()
            except Exception:
                time.sleep(1)

    def current(self):
        if self.fix and time.time() - self.fix_time <= self.max_age_s:
            return self.fix
        return None


def resolve_location(image_path=None, gps=None, manual=None, browser=None):
    """Priority: photo EXIF > GPS hardware > browser/phone GPS > manual entry > none.
    Never invents coordinates: returns (None, None, 'none') when nothing real is available."""
    if image_path:
        fix = exif_gps(image_path)
        if fix:
            return fix[0], fix[1], "gps_exif"
    if gps is not None:
        fix = gps.current()
        if fix:
            return fix[0], fix[1], "gps_device"
    if browser and browser[0] is not None:
        return browser[0], browser[1], "gps_browser"
    if manual and manual[0] is not None:
        return manual[0], manual[1], "manual"
    return None, None, "none"

"""
DrainX - YOLOv8 pothole detection for AquaGrid

  python pothole_detect.py --source road.jpg            one image
  python pothole_detect.py --source photos/             every image in a folder
  python pothole_detect.py --source road.mp4            a recorded video
  python pothole_detect.py --source 0                   webcam 0
  python pothole_detect.py --worker                     process uploads from the dashboard

Options:
  --segment J2              road segment (J1..J4, see segments.py)
  --lat 12.91 --lng 77.62   manual location (only if you really know it)
  --gps-port COM5           USB GPS module (NMEA) for live coordinates
  --min-conf 0.25           confidence threshold
  --no-show                 do not open a preview window
  --dry-run                 detect only, do not write to Supabase

Location is NEVER invented. Priority: photo EXIF GPS > GPS module > browser GPS (uploads)
> manual --lat/--lng > none (stored as "location unavailable").
"""
import argparse
import glob
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone

from common import env, env_float, get_db, get_logger, heartbeat, raise_alert, HERE
from drainx_ai import GpsReader, classify, model_info, pothole_boxes, resolve_location
from segments import SEGMENTS, segment_name

log = get_logger("drainx")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
VIDEO_EXT = (".mp4", ".avi", ".mov", ".mkv")
COOLDOWN_S = 5           # at most one record per 5 s of video / webcam
ANNOTATED_DIR = os.path.join(HERE, "detections")


def model_path():
    p = env("POTHOLE_MODEL", "models/best.pt", required=False)
    return p if os.path.isabs(p) else os.path.join(HERE, p)


class Detector:
    def __init__(self, args):
        self.args = args
        self.info = model_info(model_path())
        self.db = None if args.dry_run else get_db()
        if not self.info["model_loaded"]:
            log.error(self.info["problem"])
            if self.db:
                heartbeat(self.db, "drainx", "error", **self.info)
            raise SystemExit(1)
        from ultralytics import YOLO
        self.model = YOLO(self.info["model_path"])
        self.min_conf = args.min_conf
        self.gps = GpsReader(args.gps_port) if args.gps_port else None
        self.count = 0
        os.makedirs(ANNOTATED_DIR, exist_ok=True)
        log.info("Model %s loaded (classes: %s), min confidence %.2f",
                 self.info["model_version"], self.model.names, self.min_conf)
        self.beat("ok")

    def beat(self, status="ok", **extra):
        if self.db:
            metrics = os.path.join(HERE, "models", "metrics.json")
            m = None
            if os.path.exists(metrics):
                import json
                with open(metrics) as f:
                    m = json.load(f)
            heartbeat(self.db, "drainx", status, **self.info, min_conf=self.min_conf,
                      classes=list(self.model.names.values()), detections_this_session=self.count,
                      metrics=m, gps_hardware=bool(self.gps), **extra)

    # ------------------------------------------------------------ one result -> one record
    def handle(self, result, source_type, source_ref, image_path=None, browser=None, segment=None):
        boxes = [b for b in pothole_boxes(result) if float(b.conf) >= self.min_conf]
        if not boxes:
            return None
        h, w = result.orig_shape
        area, severity = classify(boxes, h, w)
        conf = max(float(b.conf) for b in boxes)
        manual = (self.args.lat, self.args.lng)
        lat, lng, loc_src = resolve_location(image_path, self.gps, manual, browser)
        seg = segment or self.args.segment
        det_id = str(uuid.uuid4())
        stamp = datetime.now(timezone.utc)

        local = os.path.join(ANNOTATED_DIR, f"{stamp:%Y%m%d_%H%M%S}_{det_id[:8]}.jpg")
        image_url = None
        try:
            import cv2
            cv2.imwrite(local, result.plot())
            if self.db:
                key = f"annotated/{os.path.basename(local)}"
                with open(local, "rb") as f:
                    self.db.storage.from_("detections").upload(key, f.read(), {"content-type": "image/jpeg"})
                image_url = self.db.storage.from_("detections").get_public_url(key)
        except Exception as e:
            log.warning("annotated image not uploaded (%s) - kept locally at %s", e, local)

        record = {
            "detection_id": det_id, "lat": lat, "lng": lng, "location_source": loc_src,
            "confidence": round(conf, 4), "boxes": len(boxes), "road_segment": seg,
            "severity": severity, "box_area_pct": area, "source_type": source_type,
            "source_ref": source_ref, "image_url": image_url, "verification": "unverified",
            "model_version": self.info["model_version"],
        }
        self.count += 1
        where = f"{lat:.5f}, {lng:.5f} ({loc_src})" if lat is not None else "location unavailable"
        log.info("Pothole #%d | conf %.1f%% | %s severity | %s | %s", self.count, conf * 100,
                 severity, segment_name(seg), where)
        if not self.db:
            return record
        try:
            self.db.table("potholes").insert(record).execute()
        except Exception as e:
            if "column" in str(e):
                log.error("Database not upgraded - run database/002_aquagrid_upgrade.sql")
            raise
        window = stamp.strftime("%Y%m%d%H") + str(stamp.minute // 10)
        raise_alert(self.db, "pothole",
                    f"Pothole detected on {segment_name(seg)}\n"
                    f"Confidence: {conf:.0%} | Severity: {severity} (heuristic)\n"
                    f"Location: {where}\nTime: {stamp:%d %b %Y %H:%M} UTC",
                    severity="warning" if severity == "HIGH" else "info",
                    dedupe_key=f"pothole:{seg}:{window}", lat=lat, lng=lng, segment=seg)
        self.beat("ok")
        return record

    # ------------------------------------------------------------ sources
    def run_images(self, paths, browser=None, segment=None, source_type="image"):
        found = []
        for p in paths:
            for r in self.model.predict(p, conf=self.min_conf, verbose=False):
                rec = self.handle(r, source_type, os.path.basename(p), image_path=p,
                                  browser=browser, segment=segment)
                if rec:
                    found.append(rec)
                if self.args.show:
                    import cv2
                    cv2.imshow("DrainX", r.plot())
                    cv2.waitKey(1500)
            if not found or found[-1]["source_ref"] != os.path.basename(p):
                log.info("No pothole above %.2f in %s", self.min_conf, os.path.basename(p))
        return found

    def run_stream(self, source, source_type, browser=None, segment=None):
        fps = 30.0
        if source_type == "video":
            import cv2
            cap = cv2.VideoCapture(source)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.release()
        gap_frames = int(COOLDOWN_S * fps)
        last_frame, last_wall, frame, found = -10 ** 9, 0.0, 0, []
        for r in self.model.predict(source=source, stream=True, conf=self.min_conf,
                                    show=self.args.show, verbose=False):
            frame += 1
            if source_type == "video" and frame - last_frame < gap_frames:
                continue
            if source_type == "webcam" and time.time() - last_wall < COOLDOWN_S:
                continue
            ref = f"{os.path.basename(str(source))}@{frame / fps:.1f}s" if source_type == "video" else f"webcam{source}"
            rec = self.handle(r, source_type, ref, browser=browser, segment=segment)
            if rec:
                found.append(rec)
                last_frame, last_wall = frame, time.time()
        return found

    # ------------------------------------------------------------ dashboard upload queue
    def worker(self):
        log.info("Worker mode: waiting for uploads from the dashboard (DrainX page)")
        while True:
            self.beat("ok", mode="worker")
            jobs = (self.db.table("detection_jobs").select("*").eq("status", "queued")
                    .order("id").limit(5).execute().data or [])
            for job in jobs:
                self.db.table("detection_jobs").update({"status": "processing"}).eq("id", job["id"]).execute()
                try:
                    data = self.db.storage.from_("detections").download(job["file_path"])
                    suffix = os.path.splitext(job["file_path"])[1] or ".jpg"
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(data)
                        path = tmp.name
                    browser = (job.get("lat"), job.get("lng")) if job.get("lat") is not None else None
                    if browser and job.get("location_source") == "manual":
                        self.args.lat, self.args.lng = browser
                        browser = None
                    seg = job.get("segment") or self.args.segment
                    if suffix.lower() in VIDEO_EXT:
                        found = self.run_stream(path, "video", browser=browser, segment=seg)
                    else:
                        found = self.run_images([path], browser=browser, segment=seg, source_type="upload")
                    self.args.lat = self.args.lng = None
                    result = {"potholes": len(found),
                              "max_confidence": max((f["confidence"] for f in found), default=None),
                              "severity": max((f["severity"] for f in found if f["severity"]),
                                              key=["LOW", "MEDIUM", "HIGH"].index, default=None),
                              "image_url": next((f["image_url"] for f in found if f["image_url"]), None),
                              "detections": [f["detection_id"] for f in found]}
                    self.db.table("detection_jobs").update({
                        "status": "done", "result": result,
                        "processed_at": datetime.now(timezone.utc).isoformat()}).eq("id", job["id"]).execute()
                    os.unlink(path)
                except Exception as e:
                    log.error("job %s failed: %s", job["id"], e)
                    self.db.table("detection_jobs").update({"status": "failed", "error": str(e)[:300]}) \
                        .eq("id", job["id"]).execute()
            time.sleep(2)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="DrainX pothole detection")
    ap.add_argument("source_pos", nargs="?", help="same as --source (kept for the old usage)")
    ap.add_argument("--source", help="image, folder, video file or webcam index")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--segment", default=env("POTHOLE_SEGMENT", "J2", required=False), choices=list(SEGMENTS))
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lng", type=float)
    ap.add_argument("--gps-port", default=env("GPS_PORT", None, required=False))
    ap.add_argument("--min-conf", type=float, default=env_float("POTHOLE_MIN_CONF", 0.25))
    ap.add_argument("--no-show", dest="show", action="store_false")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    a.source = a.source or a.source_pos or ("0" if not a.worker else None)
    if (a.lat is None) != (a.lng is None):
        ap.error("--lat and --lng must be given together")
    return a


def main():
    args = parse_args()
    det = Detector(args)
    if args.worker:
        args.show = False
        return det.worker()
    src = args.source
    if src.isdigit():
        found = det.run_stream(int(src), "webcam")
    elif os.path.isdir(src):
        files = sorted(f for f in glob.glob(os.path.join(src, "*")) if f.lower().endswith(IMAGE_EXT))
        found = det.run_images(files)
    elif src.lower().endswith(VIDEO_EXT):
        found = det.run_stream(src, "video")
    elif src.lower().endswith(IMAGE_EXT):
        found = det.run_images([src])
    else:
        raise SystemExit(f"Unsupported source: {src}")
    log.info("Finished: %d pothole record(s) saved", len(found))
    det.beat("ok", last_run_records=len(found))


if __name__ == "__main__":
    main()

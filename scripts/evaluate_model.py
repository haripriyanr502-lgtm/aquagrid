"""
DrainX model evaluation - real metrics only.

  python evaluate_model.py --data path/to/data.yaml            (uses the 'val' split)
  python evaluate_model.py --data path/to/data.yaml --split test

Writes scripts/models/metrics.json (shown on the dashboard's System Health and DrainX pages)
and saves the confusion matrix + PR curves in scripts/models/eval/.
The dataset (data.yaml + images) is the Roboflow export you trained on.
"""
import argparse
import json
import os
from datetime import datetime, timezone

from common import HERE, env, get_logger
from drainx_ai import model_info

log = get_logger("evaluate")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="data.yaml of the YOLOv8 dataset")
    ap.add_argument("--split", default="val", choices=["val", "test"])
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()

    path = env("POTHOLE_MODEL", "models/best.pt", required=False)
    path = path if os.path.isabs(path) else os.path.join(HERE, path)
    info = model_info(path)
    if not info["model_loaded"]:
        raise SystemExit(info["problem"])

    from ultralytics import YOLO
    model = YOLO(path)
    out_dir = os.path.join(HERE, "models", "eval")
    m = model.val(data=a.data, split=a.split, conf=a.conf, plots=True,
                  project=out_dir, name=a.split, exist_ok=True, verbose=False)

    tp = fp = fn = None
    try:
        mat = m.confusion_matrix.matrix            # rows = predicted, cols = true, last = background
        nc = mat.shape[0] - 1
        idx = [i for i, n in m.names.items() if "pothole" in str(n).lower()] or list(range(nc))
        tp = int(sum(mat[i, i] for i in idx))
        fp = int(sum(mat[i, nc] for i in idx))       # predicted pothole, nothing there
        fn = int(sum(mat[nc, i] for i in idx))       # real pothole, missed
    except Exception as e:
        log.warning("could not read confusion matrix: %s", e)

    metrics = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": info["model_version"], "data": a.data, "split": a.split, "conf": a.conf,
        "precision": round(float(m.box.mp), 4), "recall": round(float(m.box.mr), 4),
        "map50": round(float(m.box.map50), 4), "map50_95": round(float(m.box.map), 4),
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "plots_dir": os.path.join(out_dir, a.split),
    }
    with open(os.path.join(HERE, "models", "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    log.info("precision %.3f | recall %.3f | mAP50 %.3f | mAP50-95 %.3f | TP %s FP %s FN %s",
             metrics["precision"], metrics["recall"], metrics["map50"], metrics["map50_95"], tp, fp, fn)
    log.info("Saved models/metrics.json and plots in %s", metrics["plots_dir"])


if __name__ == "__main__":
    main()

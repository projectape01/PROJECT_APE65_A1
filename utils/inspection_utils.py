import re

import cv2
import numpy as np


def is_good_label(label):
    text = str(label).strip().upper()
    return text in {"GOOD", "OK", "PASS"} or text.startswith("GOOD")


def is_ng_label(label):
    text = str(label).strip().upper()
    return any(token in text for token in ["NG", "DEFECT", "FAIL", "BAD", "SCRATCH", "BURR", "CRACK"])


def normalize_defect_label(label):
    text = str(label).strip().upper()
    return re.sub(r"[^A-Z0-9_]+", "_", text)


def class_conf_threshold(label, thresholds, default=0.20):
    key = normalize_defect_label(label)
    return thresholds.get(key, default)


def class_rank_score(label, probability, weights):
    key = normalize_defect_label(label)
    weight = weights.get(key, 1.0)
    return float(probability) * float(weight)


def is_scratches_label(label):
    return normalize_defect_label(label) == "DEFECT_SCRATCHES"


def choose_priority_ng(ng_detections, scratch_override_margin):
    if not ng_detections:
        return None

    scratch_only = [d for d in ng_detections if is_scratches_label(d["label"])]
    non_scratch = [d for d in ng_detections if not is_scratches_label(d["label"])]

    if non_scratch:
        best_non_scratch = max(non_scratch, key=lambda d: d["rank_score"])
        if not scratch_only:
            return best_non_scratch

        best_scratch = max(scratch_only, key=lambda d: d["rank_score"])
        if best_scratch["prob"] >= (best_non_scratch["prob"] + scratch_override_margin):
            return best_scratch
        return best_non_scratch

    return max(scratch_only, key=lambda d: d["rank_score"])


def frame_motion_diff(curr_img, prev_gray_small):
    gray = cv2.cvtColor(curr_img, cv2.COLOR_BGR2GRAY)
    gray_small = cv2.resize(gray, (160, 90))
    gray_small = cv2.GaussianBlur(gray_small, (5, 5), 0)
    if prev_gray_small is None:
        return gray_small, 999.0
    diff = cv2.absdiff(gray_small, prev_gray_small)
    return gray_small, float(np.mean(diff))


def get_label_side(label):
    text = str(label).strip().upper()
    match = re.search(r"(?:^|_)([123])(?:$|_)", text)
    if match:
        return int(match.group(1))
    return 0


def sanitize_capture_name(value):
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = text.strip("._")
    return text or "unknown"

from flask import Flask
import cv2
import datetime
import json
import numpy as np
import os
import subprocess
import threading
import time
import signal
import sys
import asyncio
from collections import Counter
from urllib.parse import quote
import urllib.error
import urllib.request
import psutil
from ultralytics import YOLO
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusDeviceContext, ModbusServerContext

from services.http_utils import (
    get_json_with_retry,
    http_session,
    post_json_pruning_unknown_columns,
    post_json_with_retry,
)
from core.project_config import (
    get_ai_runtime_settings,
    get_camera_focus_settings,
    get_capture_bucket,
    get_line_bot_settings,
    get_side3_measurement_settings,
    get_supabase_settings,
    has_printer_pairing_config,
    load_local_config,
    save_local_config,
)
from core.runtime_defaults import (
    default_ai_results,
    empty_printer_state as _empty_printer_state,
    reset_part_session,
)
from utils.inspection_utils import (
    choose_priority_ng,
    class_conf_threshold,
    class_rank_score,
    frame_motion_diff,
    get_label_side,
    is_good_label,
    is_ng_label,
    sanitize_capture_name,
)
from utils.system_utils import (
    as_float as _as_float,
    as_int as _as_int,
    can_connect_tcp,
    is_valid_ipv4,
    normalize_stage as _normalize_stage,
)
from utils.side3_measurement import (
    annotate_calibration_box_measurement,
    annotate_side3_measurement,
    measure_calibration_box_from_frame,
    measure_side3_from_frame,
)
from services.printer_service import (
    apply_printer_finish_cleanup_unlocked as _apply_printer_finish_cleanup_unlocked_impl,
    get_printer_status as get_printer_status_impl,
    on_printer_connect as on_printer_connect_impl,
    on_printer_message as on_printer_message_impl,
    reset_printer_finish_cleanup_timer as _reset_printer_finish_cleanup_timer_impl,
    start_printer_mqtt_thread as start_printer_mqtt_thread_impl,
    update_printer_finish_cleanup_timer as _update_printer_finish_cleanup_timer_impl,
)
from routes.app_routes import register_routes

app = Flask(__name__)
UTC = datetime.timezone.utc
ACTIVE_INSPECTION_SIDES = (1, 2, 3)
SIDE3_TARGETS_MM = {
    "top": 19.50,
    "bottom": 24.50,
    "length": 90.00,
}
SIDE3_TOLERANCE_MM = 0.3
SIDE3_LENGTH_OFFSET_MM = 1.3
SIDE3_MIN_BBOX_DIM_PX = 120
SIDE3_MIN_CONTOUR_AREA_RATIO = 0.01
SIDE3_SMOOTHING_ALPHA = 0.35
side3_measurement_armed = False
side3_manual_preview_enabled = False


def log_system_status_sync(message):
    print(f"[SYS_SYNC] {message}", flush=True)


def reset_dimension_state(session):
    session["dimension_top"] = None
    session["dimension_bottom"] = None
    session["dimension_length"] = None
    session["dimension_status"] = None
    session["dimension_message"] = None


def get_dimension_payload_unlocked():
    return {
        "top": part_session.get("dimension_top"),
        "bottom": part_session.get("dimension_bottom"),
        "length": part_session.get("dimension_length"),
        "status": part_session.get("dimension_status"),
        "message": part_session.get("dimension_message"),
    }


def get_side_ai_overlay_unlocked(side):
    if isinstance(locked_overlay, dict) and int(locked_overlay.get("side") or 0) == int(side):
        return locked_overlay.copy()
    if isinstance(latest_ai_results, dict) and int(latest_ai_results.get("side") or 0) == int(side):
        return latest_ai_results.copy()
    return default_ai_results(side)


def resolve_side_ai_decision_unlocked(side):
    overlay = get_side_ai_overlay_unlocked(side)
    overlay_label = str(overlay.get("label") or "").strip()
    overlay_side = int(get_label_side(overlay_label) or 0)
    overlay_is_ng = bool(overlay.get("is_ng")) and overlay_side in (0, int(side))

    if overlay_is_ng and is_ng_label(overlay_label):
        return {
            "saved_label": f"NG_{int(side)}",
            "defect_label": overlay_label,
            "overlay": overlay,
        }

    overlay["points"] = []
    overlay["detections"] = []
    overlay["is_ng"] = False
    overlay["label"] = "GOOD"
    return {
        "saved_label": f"GOOD_{int(side)}",
        "defect_label": "-",
        "overlay": overlay,
    }


def dimensions_in_spec(measurement):
    if not isinstance(measurement, dict):
        return False
    return (
        abs(float(measurement.get("top_width_mm") or 0.0) - SIDE3_TARGETS_MM["top"]) <= SIDE3_TOLERANCE_MM
        and abs(float(measurement.get("bottom_width_mm") or 0.0) - SIDE3_TARGETS_MM["bottom"]) <= SIDE3_TOLERANCE_MM
        and abs(float(measurement.get("length_mm") or 0.0) - SIDE3_TARGETS_MM["length"]) <= SIDE3_TOLERANCE_MM
    )


def apply_side3_length_offset(measurement):
    if not isinstance(measurement, dict):
        return measurement
    adjusted = measurement.copy()
    length_mm = adjusted.get("length_mm")
    if length_mm is not None:
        adjusted["length_mm"] = float(length_mm) + float(SIDE3_LENGTH_OFFSET_MM)
    return adjusted


def has_valid_side3_detection(measurement):
    if not isinstance(measurement, dict):
        return False
    bbox = measurement.get("bbox") or (0, 0, 0, 0)
    _x, _y, w, h = bbox
    if int(w) < SIDE3_MIN_BBOX_DIM_PX or int(h) < SIDE3_MIN_BBOX_DIM_PX:
        return False

    frame_w = int(measurement.get("frame_w") or 0)
    frame_h = int(measurement.get("frame_h") or 0)
    contour_area = float(measurement.get("contour_area") or 0.0)
    if frame_w <= 0 or frame_h <= 0:
        return contour_area > 0.0

    frame_area = float(frame_w * frame_h)
    if frame_area <= 0:
        return False
    return (contour_area / frame_area) >= SIDE3_MIN_CONTOUR_AREA_RATIO


def has_valid_calibration_preview(measurement):
    if not isinstance(measurement, dict):
        return False
    bbox = measurement.get("bbox") or (0, 0, 0, 0)
    _x, _y, w, h = bbox
    if int(w) < 60 or int(h) < 60:
        return False

    frame_w = int(measurement.get("frame_w") or 0)
    frame_h = int(measurement.get("frame_h") or 0)
    contour_area = float(measurement.get("contour_area") or 0.0)
    if frame_w <= 0 or frame_h <= 0:
        return contour_area > 0.0

    frame_area = float(frame_w * frame_h)
    if frame_area <= 0:
        return False
    return (contour_area / frame_area) >= 0.0025


def reset_side3_smoothing_state():
    global side3_smoothing_state
    side3_smoothing_state = None


def set_side3_measurement_armed(enabled):
    global side3_measurement_armed
    with data_lock:
        side3_measurement_armed = bool(enabled)


def is_side3_measurement_armed():
    with data_lock:
        return bool(side3_measurement_armed)


def set_side3_manual_preview_enabled(enabled):
    global side3_manual_preview_enabled
    with data_lock:
        side3_manual_preview_enabled = bool(enabled)


def is_side3_manual_preview_enabled():
    with data_lock:
        return bool(side3_manual_preview_enabled)


def _blend_scalar(prev_value, curr_value, alpha):
    return (float(prev_value) * (1.0 - alpha)) + (float(curr_value) * alpha)


def _blend_point(prev_point, curr_point, alpha):
    return [
        _blend_scalar(prev_point[0], curr_point[0], alpha),
        _blend_scalar(prev_point[1], curr_point[1], alpha),
    ]


def _blend_point_list(prev_points, curr_points, alpha):
    if not isinstance(prev_points, list) or not isinstance(curr_points, list):
        return curr_points
    if len(prev_points) != len(curr_points):
        return curr_points
    blended = []
    for prev_point, curr_point in zip(prev_points, curr_points):
        if not isinstance(prev_point, (list, tuple)) or not isinstance(curr_point, (list, tuple)):
            return curr_points
        if len(prev_point) != 2 or len(curr_point) != 2:
            return curr_points
        blended.append(_blend_point(prev_point, curr_point, alpha))
    return blended


def smooth_side3_measurement(measurement):
    global side3_smoothing_state
    if not isinstance(measurement, dict):
        return measurement
    prev = side3_smoothing_state
    if not isinstance(prev, dict):
        side3_smoothing_state = measurement.copy()
        return measurement

    alpha = float(SIDE3_SMOOTHING_ALPHA)
    smoothed = measurement.copy()
    scalar_keys = (
        "center_x",
        "center_y",
        "angle_deg",
        "major_axis_px",
        "length_px",
        "length_mm",
        "top_width_px",
        "top_width_mm",
        "bottom_width_px",
        "bottom_width_mm",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "bbox_area",
        "contour_area",
    )
    point_keys = ("axis_start", "axis_end", "top_line_start", "top_line_end", "bottom_line_start", "bottom_line_end")
    point_list_keys = ("rotated_box",)

    for key in scalar_keys:
        if prev.get(key) is not None and measurement.get(key) is not None:
            smoothed[key] = _blend_scalar(prev[key], measurement[key], alpha)

    for key in point_keys:
        if prev.get(key) and measurement.get(key):
            smoothed[key] = _blend_point(prev[key], measurement[key], alpha)

    for key in point_list_keys:
        if prev.get(key) and measurement.get(key):
            smoothed[key] = _blend_point_list(prev[key], measurement[key], alpha)

    if all(smoothed.get(k) is not None for k in ("bbox_x", "bbox_y", "bbox_w", "bbox_h")):
        smoothed["bbox"] = (
            int(round(smoothed["bbox_x"])),
            int(round(smoothed["bbox_y"])),
            int(round(smoothed["bbox_w"])),
            int(round(smoothed["bbox_h"])),
        )

    side3_smoothing_state = smoothed.copy()
    return smoothed


def compute_final_result(session):
    has_ng = any(str(session.get(f"side{i}", "")).startswith("NG_") for i in ACTIVE_INSPECTION_SIDES)
    return "NG" if has_ng else "GOOD"


def complete_part_if_ready():
    global part_session, locked_overlay, latest_ai_results, inspection_active, overlay_block_until
    global side3_measurement_armed, side3_manual_preview_enabled
    final_session = None
    final_result = None

    with data_lock:
        sides_complete = all(part_session.get(f"side{i}") for i in ACTIVE_INSPECTION_SIDES)
        if not sides_complete:
            return None

        final_session = part_session.copy()
        final_result = compute_final_result(final_session)
        part_session = reset_part_session()
        reset_dimension_state(part_session)
        reset_side_observation(1)
        reset_side3_smoothing_state()
        side3_measurement_armed = False
        side3_manual_preview_enabled = False
        locked_overlay = None
        latest_ai_results = default_ai_results(1)
        inspection_active = False
        overlay_block_until = time.time() + SIDE_SWITCH_OVERLAY_BLOCK_SEC

    trigger_modbus_signal(4 if final_result == "NG" else 3)
    log_part_to_supabase(final_session)
    return {
        "session": final_session,
        "final_result": final_result,
    }


def fetch_latest_part_id_from_supabase():
    base_url, key = get_supabase_settings()
    url = f"{base_url}/rest/v1/part_records?select=part_id&order=part_id.desc&limit=1"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        response = get_json_with_retry(url, headers, timeout=(3.0, 10.0))
        if response.status_code != 200:
            return 0
        payload = response.json()
        if isinstance(payload, list) and payload:
            return int(payload[0].get("part_id") or 0)
    except Exception:
        pass
    return 0


def fetch_latest_part_id_from_local():
    latest_local = 0

    def _update_from_name(name):
        nonlocal latest_local
        if not name.startswith("part_"):
            return
        digits = []
        for ch in name[5:]:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            return
        try:
            latest_local = max(latest_local, int("".join(digits)))
        except Exception:
            pass

    try:
        for entry in os.listdir(CAPTURES_DIR):
            _update_from_name(entry)
    except Exception:
        pass

    try:
        for entry in os.listdir(RUNTIME_STATE_DIR):
            _update_from_name(entry)
    except Exception:
        pass

    return latest_local


def get_capture_part_ids():
    part_ids = set()
    try:
        for entry in os.listdir(CAPTURES_DIR):
            if not entry.startswith("part_"):
                continue
            digits = []
            for ch in entry[5:]:
                if ch.isdigit():
                    digits.append(ch)
                else:
                    break
            if not digits:
                continue
            part_id = int("".join(digits))
            if part_id > 0:
                part_ids.add(part_id)
    except Exception:
        pass
    return part_ids


def find_first_missing_positive(values):
    candidate = 1
    used = set(int(v) for v in values if int(v) > 0)
    while candidate in used:
        candidate += 1
    return candidate


def read_part_counter_state():
    state_path = os.path.join(RUNTIME_STATE_DIR, "_part_counter.json")
    try:
        if not os.path.exists(state_path):
            return 0
        with open(state_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return int(payload.get("last_part_id") or 0)
    except Exception:
        return 0


def write_part_counter_state(part_id):
    state_path = os.path.join(RUNTIME_STATE_DIR, "_part_counter.json")
    try:
        os.makedirs(RUNTIME_STATE_DIR, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "last_part_id": int(part_id or 0),
                    "updated_at": datetime.datetime.now().isoformat(),
                },
                fh,
                ensure_ascii=True,
            )
    except Exception:
        pass


def resolve_latest_part_id():
    latest_db = int(fetch_latest_part_id_from_supabase() or 0)
    latest_local = int(fetch_latest_part_id_from_local() or 0)
    latest_state = int(read_part_counter_state() or 0)
    with data_lock:
        active_part_id = int(part_session.get("part_id") or 0)
        current_total = int(total_parts_inspected or 0)
    resolved = max(latest_db, latest_local, latest_state, active_part_id, current_total)
    print(
        f"[PART] resolve_latest_part_id db={latest_db} local={latest_local} state={latest_state} "
        f"active={active_part_id} total={current_total} -> {resolved}",
        flush=True,
    )
    return resolved


def sync_total_parts_from_supabase():
    global total_parts_inspected
    capture_ids = get_capture_part_ids()
    latest_part_id = int(max(capture_ids)) if capture_ids else 0
    with data_lock:
        total_parts_inspected = int(latest_part_id or 0)
        return total_parts_inspected


def reserve_next_part_id():
    global total_parts_inspected
    capture_ids = get_capture_part_ids()
    with data_lock:
        active_part_id = int(part_session.get("part_id") or 0)
        used_ids = set(capture_ids)
        if active_part_id > 0:
            used_ids.add(active_part_id)
        next_part = int(find_first_missing_positive(used_ids))
        total_parts_inspected = int(max(capture_ids)) if capture_ids else 0
        print(
            f"[PART] reserve_next_part_id captures_count={len(capture_ids)} active={active_part_id} "
            f"next={next_part}",
            flush=True,
        )
        try:
            os.makedirs(os.path.join(CAPTURES_DIR, f"part_{int(next_part):06d}"), exist_ok=True)
        except Exception:
            pass
        write_part_counter_state(next_part)
        return next_part


def _reset_printer_finish_cleanup_timer():
    _reset_printer_finish_cleanup_timer_impl(sys.modules[__name__])


def _update_printer_finish_cleanup_timer(status_text):
    _update_printer_finish_cleanup_timer_impl(sys.modules[__name__], status_text)


def _apply_printer_finish_cleanup_unlocked():
    _apply_printer_finish_cleanup_unlocked_impl(sys.modules[__name__])


def get_printer_status(force_refresh=False):
    return get_printer_status_impl(sys.modules[__name__], force_refresh=force_refresh)


def on_printer_connect(client, userdata, flags, rc, properties=None):
    return on_printer_connect_impl(sys.modules[__name__], client, userdata, flags, rc, properties)


def on_printer_message(client, userdata, msg):
    return on_printer_message_impl(sys.modules[__name__], client, userdata, msg)


def start_printer_mqtt_thread():
    return start_printer_mqtt_thread_impl(sys.modules[__name__])

# --- YOLO Model Setup ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AI_SETTINGS = get_ai_runtime_settings()
YOLO_MODEL_PATH = AI_SETTINGS["model_path"]
YOLO_MODEL_TASK = AI_SETTINGS["task"]
YOLO_INPUT_SIZE = AI_SETTINGS["imgsz"]
YOLO_BASE_CONF = AI_SETTINGS["base_conf"]
CAPTURES_DIR = os.path.join(BASE_DIR, "captures")
os.makedirs(CAPTURES_DIR, exist_ok=True)
RUNTIME_STATE_DIR = os.path.join(BASE_DIR, "tmp", "runtime_state")
os.makedirs(RUNTIME_STATE_DIR, exist_ok=True)
try:
    print(
        f"[AI] Loading YOLO model from {YOLO_MODEL_PATH} "
        f"(task={YOLO_MODEL_TASK}, imgsz={YOLO_INPUT_SIZE}, conf={YOLO_BASE_CONF:.2f})...",
        flush=True,
    )
    model = YOLO(YOLO_MODEL_PATH, task=YOLO_MODEL_TASK)
    print("[AI] YOLO model ready.", flush=True)
except Exception as e:
    print(f"[AI] Error: {e}", flush=True)
    model = None

# --- Modbus Setup ---
slaves_store = {1: ModbusDeviceContext(di=ModbusSequentialDataBlock(0, [0]*100), co=ModbusSequentialDataBlock(0, [0]*100), hr=ModbusSequentialDataBlock(0, [0]*100), ir=ModbusSequentialDataBlock(0, [0]*100))}
context = ModbusServerContext(devices=slaves_store, single=False)

def _append_modbus_log(addr, status):
    entry = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "addr": int(addr),
        "status": str(status),
    }
    with data_lock:
        modbus_log.append(entry)
        if len(modbus_log) > 30:
            modbus_log.pop(0)


def _set_modbus_signal(addr, value):
    addr = int(addr)
    bit_value = 1 if value else 0
    # Mirror the same address across common Modbus tables so TM Flow can read the signal
    # even if its node is configured for a different table type.
    context[1].setValues(0x01, addr, [bit_value])
    context[1].setValues(0x02, addr, [bit_value])
    context[1].setValues(0x03, addr, [bit_value])
    context[1].setValues(0x04, addr, [bit_value])


def trigger_modbus_signal(addr):
    try:
        _set_modbus_signal(addr, True)
        def reset():
            time.sleep(2)
            _set_modbus_signal(addr, False)
        threading.Thread(target=reset, daemon=True).start()
        _append_modbus_log(addr, "SENT")
    except Exception:
        _append_modbus_log(addr, "ERROR")

async def run_modbus_server():
    await StartAsyncTcpServer(context=context, address=("0.0.0.0", 5020))

def start_modbus_thread():
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(run_modbus_server())


def get_all_ips():
    now_ts = time.time()
    if now_ts - _ip_cache["ts"] < 10.0:
        return _ip_cache["value"]

    ips = []
    try:
        ips = subprocess.check_output(["hostname", "-I"]).decode().split()
        ips = [ip for ip in ips if "." in ip]
    except Exception:
        ips = []
    _ip_cache["value"] = ips
    _ip_cache["ts"] = now_ts
    return ips


def get_robot_status():
    now_ts = time.time()
    if now_ts - _robot_status_cache["ts"] < 1.0:
        return _robot_status_cache["value"]

    status = "Disconnected"
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == 5020 and conn.status == "ESTABLISHED":
                status = "Connected"
                break
    except Exception:
        pass
    _robot_status_cache["value"] = status
    _robot_status_cache["ts"] = now_ts
    return status


def get_pi_stats():
    now_ts = time.time()
    if now_ts - _pi_stats_cache["ts"] < 2.0:
        return _pi_stats_cache["value"]

    cpu_temp = None
    try:
        temps = psutil.sensors_temperatures()
        for entries in temps.values():
            if entries:
                cpu_temp = float(entries[0].current)
                break
    except Exception:
        cpu_temp = None

    stats = {
        "cpu_usage": psutil.cpu_percent(),
        "ram_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage("/").percent,
        "cpu_temp": cpu_temp,
    }
    _pi_stats_cache["value"] = stats
    _pi_stats_cache["ts"] = now_ts
    return stats

# --- Global States ---
latest_frame = None
latest_raw_frame = None
latest_ai_results = default_ai_results(1)
frame_lock = threading.Lock()
camera_proc_lock = threading.Lock()
data_lock = threading.RLock()
system_on = True
current_zoom_index = 0
current_camera_lens_position = float(get_camera_focus_settings().get("lens_position") or 6.0)
camera_pause_event = threading.Event()
camera_stream_proc = None
inspection_history = []
modbus_log = []
total_parts_inspected = 0
_robot_status_cache = {"value": "Disconnected", "ts": 0.0}
_pi_stats_cache = {"value": {"cpu_usage": 0, "ram_usage": 0, "disk_usage": 0, "cpu_temp": None}, "ts": 0.0}
_ip_cache = {"value": [], "ts": 0.0}
_printer_status_cache = {
    "value": _empty_printer_state(None),
    "ts": 0.0,
}
_printer_mqtt_client = None
_printer_reconnect_event = threading.Event()
_printer_post_finish_armed = False
_printer_post_finish_deadline_ts = 0.0
_printer_finish_signal_sent = False
_printer_finish_cleared = False

# --- Part Session (Sequential 3 Sides) ---
side_observation = {}
side3_smoothing_state = None
locked_overlay = None
inspection_active = False
AI_INTERVAL_SEC = 0.18
STREAM_INTERVAL_SEC = 0.08
SIDE_SWITCH_OVERLAY_BLOCK_SEC = 2.0
overlay_block_until = 0.0
CLASS_CONF_THRESHOLDS = {
    "DEFECT_HOLE": 0.18,
    "DEFECT_SCRAP": 0.18,
    "DEFECT_SCRATCHES": 0.72,
}
CLASS_SCORE_WEIGHTS = {
    "DEFECT_HOLE": 1.25,
    "DEFECT_SCRAP": 1.20,
    "DEFECT_SCRATCHES": 0.90,
}
SCRATCH_OVERRIDE_MARGIN = 0.22
YOLO_STABLE_DIFF_THRESHOLD = 6.0
YOLO_STABLE_REQUIRED_FRAMES = 7


def get_raw_frame_snapshot():
    with frame_lock:
        if latest_raw_frame is None:
            return None
        return latest_raw_frame.copy()


def get_camera_focus_payload():
    with data_lock:
        return {
            "lens_position": float(current_camera_lens_position),
            "mode": "manual",
        }


def set_camera_lens_position(value, persist=True):
    global current_camera_lens_position
    try:
        lens_position = float(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid lens position.")

    if lens_position < 0.0 or lens_position > 32.0:
        raise ValueError("Lens position must be between 0.0 and 32.0.")

    with data_lock:
        current_camera_lens_position = lens_position

    if persist:
        cfg = load_local_config()
        cfg["CAMERA_LENS_POSITION"] = lens_position
        save_local_config(cfg)

    return lens_position


def render_overlay_frame(frame, overlay):
    view = frame.copy()
    res = overlay if isinstance(overlay, dict) else {}

    with data_lock:
        active_inspection = inspection_active
        current_side = part_session.get("current_side", 1)
        side3_armed = side3_measurement_armed
        side3_preview = side3_manual_preview_enabled

    if side3_preview:
        try:
            measure_settings = get_side3_measurement_settings()
            preview_cfg = load_local_config()
            calibration_measurement = measure_calibration_box_from_frame(
                frame,
                measure_settings["scale_mm_per_pixel"],
                preview_cfg.get("SIDE3_GAGEBOX_HEIGHT_MM"),
            )
            return annotate_calibration_box_measurement(view, calibration_measurement)
        except Exception as exc:
            log_system_status_sync(f"calibration preview failed: {exc}")

    # Handle Side 3 OpenCV Measurement Drawing
    side3_measure = res.get("side3_measurement")
    if not side3_measure:
        if active_inspection and current_side == 3 and side3_armed:
            try:
                measure_settings = get_side3_measurement_settings()
                live_measurement = measure_side3_from_frame(
                    frame,
                    measure_settings["scale_mm_per_pixel"],
                )
                live_measurement = smooth_side3_measurement(live_measurement)
                live_measurement = apply_side3_length_offset(live_measurement)
                if has_valid_side3_detection(live_measurement):
                    side3_measure = live_measurement
            except Exception:
                side3_measure = None
    if side3_measure:
        view = annotate_side3_measurement(view, side3_measure, saved_label=res.get("label"))

    detections = res.get("detections") or []
    if not detections:
        points = res.get("points") or []
        if points:
            detections = [{
                "label": res.get("label", "---"),
                "prob": res.get("prob", 0),
                "points": points,
                "is_ng": res.get("is_ng", False),
                "side": res.get("side", "-"),
                "is_primary": True,
            }]

    if detections:
        h, w = view.shape[:2]
        sx, sy = w / float(YOLO_INPUT_SIZE), h / float(YOLO_INPUT_SIZE)
        font = cv2.FONT_HERSHEY_SIMPLEX
        ordered_detections = sorted(
            detections,
            key=lambda item: (not bool(item.get("is_primary")), -float(item.get("prob") or 0.0)),
        )
        for detection in ordered_detections:
            points = detection.get("points") or []
            if len(points) < 4:
                continue

            pts = np.array([[int(p[0] * sx), int(p[1] * sy)] for p in points], np.int32)
            is_primary = bool(detection.get("is_primary"))
            color = (0, 0, 255) if detection.get("is_ng") else (0, 255, 0)
            thickness = 4 if is_primary else 2
            cv2.polylines(view, [pts.reshape((-1, 1, 2))], True, color, thickness, cv2.LINE_AA)

            txt = f"S{detection.get('side', '-') } - {str(detection.get('label', '---')).upper()}"
            txt += f" {(float(detection.get('prob') or 0.0) * 100):.0f}%"
            (tw, th), _ = cv2.getTextSize(txt, font, 0.65, 2)
            top_left = (max(0, pts[0][0]), max(th + 10, pts[0][1]))
            cv2.rectangle(view, (top_left[0], top_left[1] - th - 10), (top_left[0] + tw + 10, top_left[1]), color, -1)
            cv2.putText(view, txt, (top_left[0] + 5, top_left[1] - 5), font, 0.65, (255, 255, 255), 2)

    return view


def get_rendered_frame_snapshot():
    with frame_lock:
        if latest_frame is None:
            return None
        frame = latest_frame.copy()
    with data_lock:
        overlay = latest_ai_results.copy()
    return render_overlay_frame(frame, overlay)


def upload_capture_to_supabase(local_path, capture_meta):
    base_url, key = get_supabase_settings()
    bucket = get_capture_bucket()
    storage_path = str(capture_meta.get("storage_path") or "")
    if not storage_path:
        return

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    encoded_storage_path = quote(storage_path, safe="/")
    storage_url = f"{base_url}/storage/v1/object/{bucket}/{encoded_storage_path}"
    public_url = f"{base_url}/storage/v1/object/public/{bucket}/{encoded_storage_path}"

    try:
        with open(local_path, "rb") as fh:
            file_headers = dict(headers)
            file_headers["Content-Type"] = "image/jpeg"
            file_headers["x-upsert"] = "true"
            response = http_session.post(storage_url, data=fh.read(), headers=file_headers, timeout=(3.0, 20.0))
        if response.status_code not in (200, 201):
            print(f"[CAPTURE] Storage upload failed ({response.status_code}): {response.text[:200]}", flush=True)
            return
    except Exception as e:
        print(f"[CAPTURE] Storage upload error: {e}", flush=True)
        return

    print(f"[CAPTURE] Uploaded side {capture_meta.get('side')} for part {capture_meta.get('part_id')}", flush=True)


def save_capture_frame(frame, side, saved_label, defect_label="-", source_label=None, part_id=None):
    if frame is None:
        return None

    captured_at_dt = datetime.datetime.now()
    captured_at = captured_at_dt.isoformat()
    resolved_part_id = int(part_id or 0)
    if resolved_part_id <= 0:
        with data_lock:
            resolved_part_id = total_parts_inspected + 1

    file_token = captured_at_dt.strftime("%Y%m%d_%H%M%S_%f")
    side_name = sanitize_capture_name(f"side_{side}")
    result_name = sanitize_capture_name(saved_label or "unknown")
    filename = f"part_{resolved_part_id:06d}_{side_name}_{result_name}_{file_token}.jpg"
    local_dir = os.path.join(CAPTURES_DIR, f"part_{resolved_part_id:06d}")
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        return None
    with open(local_path, "wb") as fh:
        fh.write(buf.tobytes())

    base_url, _ = get_supabase_settings()
    bucket = get_capture_bucket()
    public_url = f"{base_url}/storage/v1/object/public/{bucket}/{quote(f'part_{resolved_part_id:06d}/{filename}', safe='/')}"

    capture_meta = {
        "part_id": resolved_part_id,
        "side": int(side),
        "saved_label": str(saved_label or ""),
        "defect_label": str(defect_label or "-"),
        "source_label": str(source_label or ""),
        "is_ng": str(saved_label or "").upper().startswith("NG"),
        "captured_at": captured_at,
        "storage_path": f"part_{resolved_part_id:06d}/{filename}",
        "local_path": local_path,
        "public_url": public_url,
    }
    threading.Thread(target=upload_capture_to_supabase, args=(local_path, capture_meta), daemon=True).start()
    return capture_meta


def capture_current_side_result(side, saved_label, defect_label="-", source_label=None, overlay_snapshot=None, part_id=None, frame_override=None):
    if isinstance(frame_override, np.ndarray):
        frame = frame_override.copy()
    else:
        with frame_lock:
            if latest_frame is None:
                return None
            frame = latest_frame.copy()

    overlay = overlay_snapshot.copy() if isinstance(overlay_snapshot, dict) else {}
    if not overlay:
        with data_lock:
            overlay = latest_ai_results.copy()

    if int(overlay.get("side") or side) != int(side):
        overlay["side"] = int(side)
    if str(saved_label or "").upper().startswith("GOOD"):
        overlay["points"] = []
        overlay["is_ng"] = False
        overlay["label"] = "GOOD"

    rendered = frame if isinstance(frame_override, np.ndarray) else render_overlay_frame(frame, overlay)
    return save_capture_frame(
        rendered,
        side=side,
        saved_label=saved_label,
        defect_label=defect_label,
        source_label=source_label or overlay.get("label"),
        part_id=part_id,
    )


part_session = reset_part_session()


def clear_runtime_state():
    global latest_ai_results, inspection_history, total_parts_inspected
    global part_session, locked_overlay, inspection_active, overlay_block_until
    global side3_measurement_armed, side3_manual_preview_enabled

    latest_part_id = resolve_latest_part_id()
    with data_lock:
        latest_ai_results = default_ai_results(1)
        inspection_history.clear()
        total_parts_inspected = latest_part_id
        part_session = reset_part_session()
        reset_dimension_state(part_session)
        reset_side3_smoothing_state()
        side3_measurement_armed = False
        side3_manual_preview_enabled = False
        locked_overlay = None
        inspection_active = False
        overlay_block_until = 0.0
        reset_side_observation(1)


def reset_side_observation(side):
    global side_observation
    side_observation = {
        "side": side,
        "defects": {},
        "last_label": None,
        "last_start": 0.0,
    }


def _record_side_observation_unlocked(label, now_ts):
    if label in {None, "---"}:
        return
    if side_observation.get("side") != part_session["current_side"]:
        reset_side_observation(part_session["current_side"])

    if side_observation["last_label"] == label and side_observation["last_start"] > 0:
        return

    last_label = side_observation.get("last_label")
    last_start = side_observation.get("last_start", 0.0)
    if last_label and is_ng_label(last_label) and last_start > 0:
        elapsed = max(0.0, now_ts - last_start)
        side_observation["defects"][last_label] = side_observation["defects"].get(last_label, 0.0) + elapsed

    side_observation["last_label"] = label
    side_observation["last_start"] = now_ts


def record_side_observation(label, now_ts):
    with data_lock:
        _record_side_observation_unlocked(label, now_ts)


def start_inspection_session():
    global part_session, locked_overlay, latest_ai_results, inspection_active, overlay_block_until
    global side3_measurement_armed, side3_manual_preview_enabled
    next_part_id = reserve_next_part_id()
    print(f"[PART] start_inspection_session next_part_id={next_part_id}", flush=True)
    # Create part folder immediately so the next part id is visible on disk
    # before the first side capture is saved.
    try:
        os.makedirs(os.path.join(CAPTURES_DIR, f"part_{int(next_part_id):06d}"), exist_ok=True)
    except Exception:
        pass
    with data_lock:
        part_session = reset_part_session()
        part_session["part_id"] = next_part_id
        reset_dimension_state(part_session)
        reset_side3_smoothing_state()
        side3_measurement_armed = False
        side3_manual_preview_enabled = False
        locked_overlay = None
        latest_ai_results = default_ai_results(1)
        inspection_active = True
        overlay_block_until = time.time() + SIDE_SWITCH_OVERLAY_BLOCK_SEC
        reset_side_observation(1)


def _close_current_defect_window_unlocked(now_ts):
    last_label = side_observation.get("last_label")
    last_start = side_observation.get("last_start", 0.0)
    if last_label and is_ng_label(last_label) and last_start > 0:
        elapsed = max(0.0, now_ts - last_start)
        side_observation["defects"][last_label] = side_observation["defects"].get(last_label, 0.0) + elapsed


def close_current_defect_window(now_ts):
    with data_lock:
        _close_current_defect_window_unlocked(now_ts)


def finalize_current_side(side, tm_label):
    global part_session, locked_overlay, latest_ai_results, inspection_active, overlay_block_until
    global side3_measurement_armed
    now_ts = time.time()
    side_key = f"side{side}"
    defect_key = f"defect_s{side}"
    last_active_side = ACTIVE_INSPECTION_SIDES[-1]
    frame_for_measurement = get_raw_frame_snapshot() if side == 3 else None

    with data_lock:
        if side != 3:
            _record_side_observation_unlocked(tm_label, now_ts)
            _close_current_defect_window_unlocked(now_ts)
        current_part_id = int(part_session.get("part_id") or 0)
        if current_part_id <= 0:
            current_part_id = reserve_next_part_id()
            part_session["part_id"] = current_part_id

        if side == 3:
            part_session[side_key] = None
            part_session[defect_key] = None
            capture_overlay = (
                locked_overlay.copy()
                if inspection_active and isinstance(locked_overlay, dict) and locked_overlay.get("side") == side
                else latest_ai_results.copy()
            )
        else:
            ai_decision = resolve_side_ai_decision_unlocked(side)
            part_session[side_key] = ai_decision["saved_label"]
            part_session[defect_key] = ai_decision["defect_label"]
            capture_overlay = ai_decision["overlay"]

            print(
                f"[AI] S{side} Confirmed by YOLO: {part_session[side_key]} / {part_session[defect_key]}",
                flush=True,
            )

        saved_label = part_session[side_key]
        defect_label = part_session[defect_key]
        pending_part_id = current_part_id
        locked_overlay = None
        next_side = None if side >= last_active_side else side + 1
        final_session = None
        final_result = None
        measurement_payload = None
        measurement_message = None

        if side < last_active_side:
            part_session["current_side"] += 1
            reset_side_observation(part_session["current_side"])
            if part_session["current_side"] == 3:
                side3_measurement_armed = False
        else:
            inspection_active = False
            side3_measurement_armed = False

        latest_ai_results = default_ai_results(next_side or 1)
        overlay_block_until = time.time() + SIDE_SWITCH_OVERLAY_BLOCK_SEC

    annotated_frame = None
    if side == 3:
        if frame_for_measurement is None:
            measurement_message = "No SIDE3 frame available for measurement."
            saved_label = "NG_3"
            defect_label = "MEASURE ERROR"
            with data_lock:
                part_session[side_key] = saved_label
                part_session[defect_key] = defect_label
                part_session["dimension_status"] = "error"
                part_session["dimension_message"] = measurement_message
        else:
            try:
                measure_settings = get_side3_measurement_settings()
                measurement = measure_side3_from_frame(
                    frame_for_measurement,
                    measure_settings["scale_mm_per_pixel"],
                )
                measurement = smooth_side3_measurement(measurement)
                measurement = apply_side3_length_offset(measurement)
                in_spec = dimensions_in_spec(measurement)
                saved_label = "GOOD_3" if in_spec else "NG_3"
                defect_label = "-" if in_spec else "DIMENSION NG"
                measurement_message = (
                    "SIDE3 dimensions detected: "
                    f"T={float(measurement.get('top_width_mm') or 0.0):.3f} mm, "
                    f"L={float(measurement.get('length_mm') or 0.0):.3f} mm, "
                    f"B={float(measurement.get('bottom_width_mm') or 0.0):.3f} mm."
                )
                measurement_payload = {
                    "top": round(float(measurement.get("top_width_mm") or 0.0), 3),
                    "bottom": round(float(measurement.get("bottom_width_mm") or 0.0), 3),
                    "length": round(float(measurement.get("length_mm") or 0.0), 3),
                    "status": "pass" if in_spec else "fail",
                    "message": measurement_message,
                }
                annotated_frame = annotate_side3_measurement(frame_for_measurement, measurement, saved_label=saved_label)
                with data_lock:
                    latest_ai_results = {
                        "side": 3,
                        "label": saved_label,
                        "is_ng": saved_label.startswith("NG"),
                        "side3_measurement": measurement,
                    }
                    part_session[side_key] = saved_label
                    part_session[defect_key] = defect_label
                    part_session["dimension_top"] = measurement_payload["top"]
                    part_session["dimension_bottom"] = measurement_payload["bottom"]
                    part_session["dimension_length"] = measurement_payload["length"]
                    part_session["dimension_status"] = measurement_payload["status"]
                    part_session["dimension_message"] = measurement_message
            except Exception as exc:
                measurement_message = f"SIDE3 measurement failed: {exc}"
                saved_label = "NG_3"
                defect_label = "MEASURE ERROR"
                with data_lock:
                    part_session[side_key] = saved_label
                    part_session[defect_key] = defect_label
                    part_session["dimension_status"] = "error"
                    part_session["dimension_message"] = measurement_message

    capture_meta = capture_current_side_result(
        side=side,
        saved_label=saved_label,
        defect_label=defect_label,
        source_label="SIDE3_OPENCV" if side == 3 else tm_label,
        overlay_snapshot={} if side == 3 else capture_overlay,
        part_id=pending_part_id,
        frame_override=annotated_frame,
    )
    if capture_meta:
        with data_lock:
            part_session[f"capture_s{side}"] = capture_meta.get("public_url")

    if side >= last_active_side:
        completion = complete_part_if_ready()
        if completion:
            final_session = completion["session"]
            final_result = completion["final_result"]

    return {
        "saved_label": saved_label,
        "defect_label": defect_label,
        "part_complete": final_session is not None,
        "next_side": next_side,
        "final_result": final_result,
        "dimensions": measurement_payload,
        "measurement_message": measurement_message,
    }

def _build_part_record_payload(session, curr_id, ts, res, defect_s1, defect_s2, defect_s3):
    return {
        "part_id": curr_id,
        "record_timestamp": ts,
        "side1": session["side1"],
        "side2": session["side2"],
        "side3": session["side3"],
        "defect _s1": defect_s1,
        "defect _s2": defect_s2,
        "defect _s3": defect_s3,
        "capture_s1": session.get("capture_s1"),
        "capture_s2": session.get("capture_s2"),
        "capture_s3": session.get("capture_s3"),
        "dimension of top": session.get("dimension_top"),
        "dimension of bottom": session.get("dimension_bottom"),
        "dimension of length": session.get("dimension_length"),
        "result": res,
    }


def _is_bigint_insert_error(response_text):
    return "invalid input syntax for type bigint" in str(response_text or "").lower()


def _line_api_request(endpoint, payload):
    settings = get_line_bot_settings()
    access_token = str(settings.get("channel_access_token") or "").strip()
    if not access_token:
        raise ValueError("LINE channel access token is not configured.")

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LINE API failed: HTTP {exc.code} {response_body}") from exc


def get_line_alert_recipients():
    recipients = []
    try:
        base_url, key = get_supabase_settings()
        select = quote("user_id", safe=",")
        url = f"{base_url}/rest/v1/line_subscribers?select={select}&subscribed=eq.true"
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        response = get_json_with_retry(url, headers, timeout=(3.0, 10.0))
        if getattr(response, "status_code", None) == 200:
            parsed = response.json()
            if isinstance(parsed, list):
                recipients = [
                    str(row.get("user_id") or "").strip()
                    for row in parsed
                    if isinstance(row, dict) and str(row.get("user_id") or "").strip()
                ]
    except Exception as exc:
        print(f"[LINE] subscriber lookup failed: {exc}", flush=True)

    if not recipients:
        fallback = str(get_line_bot_settings().get("target_user_id") or "").strip()
        if fallback:
            recipients = [fallback]
    return list(dict.fromkeys(recipients))


def _push_line_messages(messages):
    normalized_messages = [msg for msg in (messages or []) if isinstance(msg, dict)]
    if not normalized_messages:
        raise ValueError("LINE push payload is incomplete.")
    results = []
    for target_user_id in get_line_alert_recipients():
        payload = {
            "to": target_user_id,
            "notificationDisabled": False,
            "messages": normalized_messages,
        }
        results.append(_line_api_request("https://api.line.me/v2/bot/message/push", payload))
    if not results:
        raise ValueError("LINE alert recipients are not configured.")
    return results


LINE_PI_ALERT_STATE_PATH = os.path.join(RUNTIME_STATE_DIR, "line_pi_alert_state.json")
LINE_PI_ALERT_COOLDOWN_SEC = 120
LINE_DAILY_SUMMARY_STATE_PATH = os.path.join(RUNTIME_STATE_DIR, "line_daily_summary_state.json")
LINE_DAILY_SUMMARY_CHECK_SEC = 30
_line_pi_alert_lock = threading.Lock()
_line_pi_shutdown_sent = False


def _load_line_pi_alert_state():
    try:
        if os.path.exists(LINE_PI_ALERT_STATE_PATH):
            with open(LINE_PI_ALERT_STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_line_pi_alert_state(state):
    try:
        with open(LINE_PI_ALERT_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state or {}, fh, ensure_ascii=True)
    except Exception:
        pass


def _push_line_text(text):
    settings = get_line_bot_settings()
    target_user_id = str(settings.get("target_user_id") or "").strip()
    payload = {
        "to": target_user_id,
        "notificationDisabled": False,
        "messages": [{"type": "text", "text": str(text or "").strip() or "APE65 A1"}],
    }
    if not payload["to"]:
        raise ValueError("LINE target user ID is not configured.")
    return _line_api_request("https://api.line.me/v2/bot/message/push", payload)


def _load_line_daily_summary_state():
    try:
        if os.path.exists(LINE_DAILY_SUMMARY_STATE_PATH):
            with open(LINE_DAILY_SUMMARY_STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_line_daily_summary_state(state):
    try:
        with open(LINE_DAILY_SUMMARY_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state or {}, fh, ensure_ascii=True)
    except Exception:
        pass


def fetch_today_line_summary():
    local_now = datetime.datetime.now()
    start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_iso = start_of_day.strftime("%Y-%m-%d %H:%M:%S")

    base_url, key = get_supabase_settings()
    select = quote("part_id,result,side1,side2,side3,record_timestamp", safe=",")
    timestamp_filter = quote(f"gte.{start_iso}", safe=":.")
    url = (
        f"{base_url}/rest/v1/part_records"
        f"?select={select}"
        f"&record_timestamp={timestamp_filter}"
        f"&order=part_id.asc"
    )
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    response = get_json_with_retry(url, headers, timeout=(3.0, 10.0))
    rows = []
    try:
        if getattr(response, "status_code", None) == 200:
            parsed = response.json()
            rows = parsed if isinstance(parsed, list) else []
    except Exception:
        rows = []

    total = len(rows)
    good = sum(1 for row in rows if str(row.get("result") or "").upper() == "GOOD")
    ng = sum(1 for row in rows if str(row.get("result") or "").upper() == "NG")
    first_part_id = 0
    latest_part_id = 0
    for row in rows:
        part_id = int(row.get("part_id") or 0)
        if part_id <= 0:
            continue
        if first_part_id <= 0:
            first_part_id = part_id
        latest_part_id = max(latest_part_id, part_id)

    yield_pct = (good / total * 100.0) if total > 0 else 0.0
    return {
        "date": local_now.strftime("%Y-%m-%d"),
        "time": local_now.strftime("%H:%M:%S"),
        "total": total,
        "good": good,
        "ng": ng,
        "yield_pct": yield_pct,
        "first_part_id": first_part_id,
        "latest_part_id": latest_part_id,
    }


def _build_daily_summary_flex(summary, reason_label):
    total = int(summary.get("total") or 0)
    good = int(summary.get("good") or 0)
    ng = int(summary.get("ng") or 0)
    yield_pct = float(summary.get("yield_pct") or 0.0)
    date_text = str(summary.get("date") or "-")
    first_part_id = int(summary.get("first_part_id") or 0)
    latest_part_id = int(summary.get("latest_part_id") or 0)
    if first_part_id > 0 and latest_part_id > 0:
        part_range_text = f"PART {first_part_id} - PART {latest_part_id}"
    else:
        part_range_text = "-"
    accent_color = "#10B981" if total > 0 and ng == 0 else "#F59E0B" if total > 0 else "#64748B"

    def metric_box(label, value, color):
        return {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "paddingAll": "12px",
            "backgroundColor": "#111827",
            "cornerRadius": "12px",
            "contents": [
                {"type": "text", "text": label, "size": "xs", "color": "#94A3B8", "weight": "bold"},
                {"type": "text", "text": value, "size": "xl", "weight": "bold", "color": color},
            ],
        }

    def summary_row(label, value, color="#111827", wrap=True, value_size="sm"):
        return {
            "type": "box",
            "layout": "horizontal",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#94A3B8", "flex": 5},
                {"type": "text", "text": str(value), "size": value_size, "weight": "bold", "align": "end", "color": color, "flex": 4, "wrap": wrap},
            ],
        }

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0F172A",
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "APE65 A1 DAILY SUMMARY", "size": "xs", "color": "#CBD5E1", "weight": "bold"},
                {"type": "text", "text": f"{yield_pct:.2f}%", "margin": "md", "size": "xxl", "weight": "bold", "color": accent_color},
                {"type": "text", "text": reason_label, "margin": "sm", "size": "sm", "color": "#94A3B8", "wrap": True},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "md",
                    "contents": [
                        metric_box("Total", str(total), "#E2E8F0"),
                        metric_box("GOOD", str(good), "#10B981"),
                        metric_box("NG", str(ng), "#EF4444"),
                    ],
                },
                {"type": "separator", "margin": "md"},
                summary_row("Summary Date", date_text, "#111827"),
                summary_row("Part Range", part_range_text, "#111827", wrap=False, value_size="xs"),
            ],
        },
    }


def send_daily_summary_if_needed(trigger_reason):
    summary = fetch_today_line_summary()
    latest_part_id = int(summary.get("latest_part_id") or 0)
    state = _load_line_daily_summary_state()
    last_sent_part_id = int(state.get("last_sent_part_id") or 0)
    today_key = str(summary.get("date") or "")
    last_1630_date = str(state.get("last_1630_date") or "")

    reason_key = str(trigger_reason or "").strip().lower()
    reason_label = "Automatic summary"
    if reason_key == "scheduled_1630":
        if last_1630_date == today_key:
            return False
        if latest_part_id <= last_sent_part_id:
            state["last_1630_date"] = today_key
            _save_line_daily_summary_state(state)
            return False
        reason_label = "Scheduled summary at 16:30"
    elif reason_key == "pi_offline":
        reason_label = "Summary before Raspberry Pi shutdown"
    else:
        if latest_part_id <= last_sent_part_id:
            return False

    _push_line_flex(
        f"APE65 A1 DAILY SUMMARY {today_key}",
        _build_daily_summary_flex(summary, reason_label),
    )

    state["last_sent_part_id"] = latest_part_id
    state["last_sent_at"] = datetime.datetime.now().isoformat()
    if reason_key == "scheduled_1630":
        state["last_1630_date"] = today_key
    _save_line_daily_summary_state(state)
    return True


def daily_summary_scheduler_thread():
    while True:
        try:
            now = datetime.datetime.now()
            if (now.hour, now.minute) >= (16, 30):
                send_daily_summary_if_needed("scheduled_1630")
        except Exception as exc:
            print(f"[LINE] Daily summary scheduler failed: {exc}", flush=True)
        time.sleep(LINE_DAILY_SUMMARY_CHECK_SEC)


def _push_line_flex(alt_text, contents):
    return _push_line_messages([{
        "type": "flex",
        "altText": str(alt_text or "APE65 A1"),
        "contents": contents,
    }])


def _build_pi_status_alert_flex(status_text):
    normalized = str(status_text or "").upper().strip()
    is_online = normalized == "ONLINE"
    header_bg = "#14532D" if is_online else "#7F1D1D"
    eyebrow = "#BBF7D0" if is_online else "#FECACA"
    hint = "#86EFAC" if is_online else "#FCA5A5"
    value_color = "#10B981" if is_online else "#EF4444"
    timestamp_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def row(label, value, color="#0F172A"):
        return {
            "type": "box",
            "layout": "horizontal",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#475569", "flex": 4},
                {"type": "text", "text": str(value), "size": "sm", "weight": "bold", "align": "end", "color": color, "flex": 5, "wrap": True},
            ],
        }

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": header_bg,
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "SYSTEM ALERT", "size": "xs", "color": eyebrow, "weight": "bold"},
                {"type": "text", "text": f"RASPBERRY PI {normalized}", "margin": "md", "size": "xl", "weight": "bold", "color": "#FFFFFF", "wrap": True},
                {"type": "text", "text": "Application lifecycle notification", "margin": "sm", "size": "sm", "color": hint, "wrap": True},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "20px",
            "contents": [
                row("Device", "Raspberry Pi"),
                row("Status", normalized, value_color),
                {"type": "separator", "margin": "md"},
                row("Time", timestamp_text),
            ],
        },
    }


def send_pi_status_alert(status_text):
    normalized = str(status_text or "").upper().strip()
    now_ts = time.time()
    with _line_pi_alert_lock:
        state = _load_line_pi_alert_state()
        last_status = str(state.get("last_status") or "").upper().strip()
        last_ts = float(state.get("last_ts") or 0.0)
        if normalized == last_status and (now_ts - last_ts) < LINE_PI_ALERT_COOLDOWN_SEC:
            return
        _push_line_flex(
            f"APE65 A1 SYSTEM ALERT Raspberry Pi {normalized}",
            _build_pi_status_alert_flex(normalized),
        )
        _save_line_pi_alert_state({
            "last_status": normalized,
            "last_ts": now_ts,
        })


def send_pi_online_alert_async():
    def _worker():
        try:
            send_pi_status_alert("ONLINE")
            print("[LINE] Raspberry Pi ONLINE alert sent", flush=True)
        except Exception as exc:
            print(f"[LINE] Raspberry Pi ONLINE alert failed: {exc}", flush=True)

    threading.Thread(target=_worker, daemon=True).start()


def send_pi_offline_alert_once():
    global _line_pi_shutdown_sent
    if _line_pi_shutdown_sent:
        return
    _line_pi_shutdown_sent = True
    try:
        send_pi_status_alert("OFFLINE")
        print("[LINE] Raspberry Pi OFFLINE alert sent", flush=True)
    except Exception as exc:
        print(f"[LINE] Raspberry Pi OFFLINE alert failed: {exc}", flush=True)


def _build_ng_alert_messages(session, curr_id, ts, defect_s1, defect_s2, defect_s3):
    side_details = []
    for side_no, side_key, defect_value, capture_key in (
        (1, "side1", defect_s1, "capture_s1"),
        (2, "side2", defect_s2, "capture_s2"),
        (3, "side3", defect_s3, "capture_s3"),
    ):
        side_value = str(session.get(side_key) or "-").upper()
        side_details.append({
            "side_no": side_no,
            "side_value": side_value or "-",
            "defect": str(defect_value or "-"),
            "capture_url": str(session.get(capture_key) or "").strip(),
        })

    failed_sides = [item for item in side_details if item["side_value"].startswith("NG_")]
    if not failed_sides and str(compute_final_result(session)).upper() != "NG":
        return []

    primary = failed_sides[0]
    recorded_at_raw = str(ts or "").strip()
    recorded_date = recorded_at_raw
    recorded_time = "-"
    if recorded_at_raw:
        normalized_recorded_at = recorded_at_raw.replace("T", " ")
        parts = normalized_recorded_at.split()
        if len(parts) >= 2:
            recorded_date = parts[0]
            recorded_time = parts[1]
        else:
            recorded_date = normalized_recorded_at

    dimension_top = session.get("dimension_top")
    dimension_bottom = session.get("dimension_bottom")
    dimension_length = session.get("dimension_length")
    has_dimensions = any(v is not None for v in (dimension_top, dimension_bottom, dimension_length))
    dim_targets = {
        "TOP": SIDE3_TARGETS_MM["top"],
        "BOTTOM": SIDE3_TARGETS_MM["bottom"],
        "LENGTH": SIDE3_TARGETS_MM["length"],
    }
    dim_tolerance = SIDE3_TOLERANCE_MM

    def row(label, value, color="#0F172A"):
        return {
            "type": "box",
            "layout": "horizontal",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#475569", "flex": 4},
                {"type": "text", "text": str(value), "size": "sm", "weight": "bold", "align": "end", "color": color, "flex": 5, "wrap": True},
            ],
        }

    body_contents = [
        row("Part ID", curr_id),
        row("Result", "NG", "#EF4444"),
        row(
            "Side 1",
            session.get("side1") or "-",
            "#EF4444" if str(session.get("side1") or "").upper().startswith("NG") else "#10B981" if str(session.get("side1") or "").upper().startswith("GOOD") else "#0F172A",
        ),
        row(
            "Side 2",
            session.get("side2") or "-",
            "#EF4444" if str(session.get("side2") or "").upper().startswith("NG") else "#10B981" if str(session.get("side2") or "").upper().startswith("GOOD") else "#0F172A",
        ),
        row(
            "Side 3",
            session.get("side3") or "-",
            "#EF4444" if str(session.get("side3") or "").upper().startswith("NG") else "#10B981" if str(session.get("side3") or "").upper().startswith("GOOD") else "#0F172A",
        ),
    ]

    defect_map = [
        ("Defect S1", defect_s1),
        ("Defect S2", defect_s2),
        ("Defect S3", defect_s3),
    ]
    if any(str(value or "-").strip() not in ("", "-") for _label, value in defect_map):
        body_contents.append({"type": "separator", "margin": "md"})
        for label, value in defect_map:
            normalized = str(value or "-").strip()
            defect_color = "#EF4444" if normalized not in ("", "-") else "#0F172A"
            body_contents.append(row(label, normalized, defect_color))

    if int(primary["side_no"]) == 3:
        body_contents.append({"type": "separator", "margin": "md"})
        for label, session_key, target in (
            ("TOP", "dimension_top", SIDE3_TARGETS_MM["top"]),
            ("BOTTOM", "dimension_bottom", SIDE3_TARGETS_MM["bottom"]),
            ("LENGTH", "dimension_length", SIDE3_TARGETS_MM["length"]),
        ):
            value = session.get(session_key)
            value_text = "-"
            value_color = "#0F172A"
            try:
                if value is not None:
                    value_float = float(value)
                    value_text = f"{value_float:.2f} mm"
                    if abs(value_float - float(target)) > float(SIDE3_TOLERANCE_MM):
                        value_color = "#EF4444"
            except Exception:
                value_text = str(value)
            body_contents.append(row(label, value_text, value_color))

    body_contents.append({"type": "separator", "margin": "md"})
    body_contents.append(row("Recorded Date", recorded_date or "-"))
    body_contents.append(row("Recorded Time", recorded_time or "-"))

    footer_contents = []
    side_buttons = [
        ("Side 1", str(session.get("capture_s1") or "").strip()),
        ("Side 2", str(session.get("capture_s2") or "").strip()),
        ("Side 3", str(session.get("capture_s3") or "").strip()),
    ]
    for label, url in side_buttons:
        if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
            continue
        footer_contents.append({
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "color": "#E2E8F0",
            "flex": 1,
            "action": {
                "type": "uri",
                "label": label,
                "uri": url,
            },
        })

    bubble = {
        "type": "flex",
        "altText": f"APE65 A1 ALERT NG Part {curr_id}",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#7F1D1D",
                "paddingAll": "20px",
                "contents": [
                    {"type": "text", "text": "APE65 A1 ALERT", "size": "xs", "color": "#FECACA", "weight": "bold"},
                    {"type": "text", "text": f"NG DETECTED PART {curr_id}", "margin": "md", "size": "xl", "weight": "bold", "color": "#FFFFFF", "wrap": True},
                    {"type": "text", "text": "Latest NG inspection record", "margin": "sm", "size": "sm", "color": "#FCA5A5", "wrap": True},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": body_contents,
            },
        },
    }
    if footer_contents:
        bubble["contents"]["footer"] = {
            "type": "box",
            "layout": "horizontal",
            "spacing": "xs",
            "paddingTop": "8px",
            "paddingBottom": "16px",
            "paddingStart": "20px",
            "paddingEnd": "20px",
            "contents": footer_contents,
        }
    return [bubble]


def send_ng_alert_async(session, curr_id, ts, defect_s1, defect_s2, defect_s3):
    def _worker():
        try:
            messages = _build_ng_alert_messages(session, curr_id, ts, defect_s1, defect_s2, defect_s3)
            if not messages:
                return
            _push_line_messages(messages)
            print(f"[LINE] NG alert sent for part {curr_id}", flush=True)
        except Exception as exc:
            print(f"[LINE] NG alert failed for part {curr_id}: {exc}", flush=True)

    threading.Thread(target=_worker, daemon=True).start()


def log_part_to_supabase(session):
    global total_parts_inspected
    defect_s1 = "-" if str(session.get("side1", "")).startswith("GOOD") else session.get("defect_s1")
    defect_s2 = "-" if str(session.get("side2", "")).startswith("GOOD") else session.get("defect_s2")
    defect_s3 = "-" if str(session.get("side3", "")).startswith("GOOD") else session.get("defect_s3")
    curr_id = int(session.get("part_id") or 0)
    if curr_id <= 0:
        curr_id = reserve_next_part_id()

    with data_lock:
        total_parts_inspected = max(int(total_parts_inspected or 0), curr_id)
        write_part_counter_state(total_parts_inspected)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        res = compute_final_result(session)

        entry = {
            "timestamp": ts,
            "part_id": curr_id,
            "status": res,
            "side1": session["side1"],
            "side2": session["side2"],
            "side3": session["side3"],
            "s1": session["side1"],
            "s2": session["side2"],
            "s3": session["side3"],
            "defect_s1": defect_s1,
            "defect_s2": defect_s2,
            "defect_s3": defect_s3,
            "capture_s1": session.get("capture_s1"),
            "capture_s2": session.get("capture_s2"),
            "capture_s3": session.get("capture_s3"),
            "dimension_top": session.get("dimension_top"),
            "dimension_bottom": session.get("dimension_bottom"),
            "dimension_length": session.get("dimension_length"),
            "dimension_status": session.get("dimension_status"),
        }
        inspection_history.append(entry)
        if len(inspection_history) > 100: inspection_history.pop(0)

    # Supabase Connection
    base_url, key = get_supabase_settings()
    url = f"{base_url}/rest/v1/part_records"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = _build_part_record_payload(session, curr_id, ts, res, defect_s1, defect_s2, defect_s3)
    try:
        response, removed_columns, sent_payload = post_json_pruning_unknown_columns(
            url,
            payload,
            headers,
            timeout=(3.0, 10.0),
        )
        if response.status_code in (200, 201):
            removed_note = f", removed={','.join(removed_columns)}" if removed_columns else ""
            print(
                f"[LOG] Part recorded. Status: {response.status_code}, keys_sent={len(sent_payload)}{removed_note}",
                flush=True,
            )
            if str(res).upper() == "NG":
                send_ng_alert_async(session.copy(), curr_id, ts, defect_s1, defect_s2, defect_s3)
            return

        print(f"[LOG] Part record failed: {response.status_code} - {response.text}", flush=True)
    except Exception as e:
        print(f"[LOG] Error: {e}", flush=True)

def ai_inference_thread():
    global latest_ai_results, locked_overlay
    print("[AI] Background Inference started.", flush=True)
    reset_side_observation(1)
    last_infer_time = 0.0
    prev_gray_small = None
    stable_frame_count = 0
    while True:
        time.sleep(0.02)
        if not system_on or model is None or latest_raw_frame is None: 
            time.sleep(0.5); continue
        now = time.time()
        if now - last_infer_time < AI_INTERVAL_SEC:
            continue
        
        try:
            with frame_lock:
                raw_frame = latest_raw_frame.copy()
            img = cv2.resize(raw_frame, (YOLO_INPUT_SIZE, YOLO_INPUT_SIZE))
            prev_gray_small, motion_diff = frame_motion_diff(img, prev_gray_small)
            if motion_diff <= YOLO_STABLE_DIFF_THRESHOLD:
                stable_frame_count += 1
            else:
                stable_frame_count = 0

            last_infer_time = now

            with data_lock:
                active_inspection = inspection_active
                current_side = part_session["current_side"] if inspection_active else 1
                block_overlay = time.time() < overlay_block_until
                side3_armed = side3_measurement_armed
            if active_inspection and current_side == 3 and side3_armed:
                side3_overlay = default_ai_results(3)
                try:
                    measure_settings = get_side3_measurement_settings()
                    side3_measurement = measure_side3_from_frame(
                        raw_frame,
                        measure_settings["scale_mm_per_pixel"],
                    )
                    side3_measurement = smooth_side3_measurement(side3_measurement)
                    side3_measurement = apply_side3_length_offset(side3_measurement)
                    if has_valid_side3_detection(side3_measurement):
                        side3_overlay = {
                            "side": 3,
                            "label": "MEASURE_3",
                            "prob": 1.0,
                            "points": [],
                            "detections": [],
                            "is_ng": False,
                            "side3_measurement": side3_measurement,
                        }
                except Exception:
                    pass
                with data_lock:
                    latest_ai_results = side3_overlay
                    locked_overlay = None
                last_infer_time = now
                continue
            require_stable = active_inspection
            is_stable_ready = (stable_frame_count >= YOLO_STABLE_REQUIRED_FRAMES)
            if require_stable and not is_stable_ready:
                with data_lock:
                    latest_ai_results = default_ai_results(current_side)
                    locked_overlay = None
                continue

            results = model(img, imgsz=YOLO_INPUT_SIZE, conf=YOLO_BASE_CONF, verbose=False)
            best_label = "---"
            best_prob = 0.0
            best_pts = []
            overlay_detections = []
            master_ng_found = False

            if results and len(results) > 0:
                res_list = results[0].obb if (hasattr(results[0], 'obb') and results[0].obb is not None) else results[0].boxes
                if res_list is not None and len(res_list) > 0:
                    all_detections = []
                    for r in res_list:
                        lbl = results[0].names[int(r.cls[0])]
                        prob = float(r.conf[0])
                        if prob < class_conf_threshold(lbl, CLASS_CONF_THRESHOLDS):
                            continue
                        if hasattr(r, 'xyxyxyxy'): pts = r.xyxyxyxy[0].tolist()
                        else: p = r.xyxy[0].tolist(); pts = [[p[0],p[1]], [p[2],p[1]], [p[2],p[3]], [p[0],p[3]]]

                        if cv2.contourArea(np.array(pts).astype(np.int32)) > 500:
                            all_detections.append({
                                "label": lbl,
                                "prob": prob,
                                "rank_score": class_rank_score(lbl, prob, CLASS_SCORE_WEIGHTS),
                                "pts": pts,
                                "is_good": is_good_label(lbl),
                                "is_ng": is_ng_label(lbl),
                                "side": get_label_side(lbl),
                            })

                    if all_detections:
                        relevant_detections = all_detections
                        if active_inspection:
                            relevant_detections = [
                                d for d in all_detections
                                if d["side"] in (0, current_side)
                            ]

                        ng_only = [d for d in relevant_detections if d["is_ng"] and d["pts"]]
                        good_only = [d for d in relevant_detections if d["is_good"]]
                        overlay_detections = [
                            {
                                "label": d["label"],
                                "prob": d["prob"],
                                "points": d["pts"],
                                "is_ng": d["is_ng"],
                                "side": current_side,
                                "is_primary": False,
                            }
                            for d in ng_only
                        ]

                        if ng_only and not block_overlay:
                            target = choose_priority_ng(ng_only, SCRATCH_OVERRIDE_MARGIN)
                            best_label = target["label"]
                            best_prob = target["prob"]
                            best_pts = target["pts"]
                            master_ng_found = True
                            for detection in overlay_detections:
                                if detection["label"] == target["label"] and detection["points"] == target["pts"]:
                                    detection["is_primary"] = True
                                    break
                            locked_overlay = {
                                "label": best_label,
                                "prob": best_prob,
                                "points": best_pts,
                                "detections": overlay_detections,
                                "is_ng": True,
                                "side": current_side,
                            }
                            if inspection_active:
                                record_side_observation(best_label, now)
                        elif good_only:
                            target = max(good_only, key=lambda d: d["rank_score"])
                            best_label = "GOOD"
                            best_prob = target["prob"]
                            best_pts = []
                            master_ng_found = False
                        elif relevant_detections and not block_overlay:
                            target = max(relevant_detections, key=lambda d: d["rank_score"])
                            best_label = target["label"]
                            best_prob = target["prob"]
                            best_pts = target["pts"] if target["is_ng"] else []
                            master_ng_found = target["is_ng"]
                            if master_ng_found and best_pts:
                                overlay_detections = [{
                                    "label": target["label"],
                                    "prob": target["prob"],
                                    "points": target["pts"],
                                    "is_ng": True,
                                    "side": current_side,
                                    "is_primary": True,
                                }]
                                locked_overlay = {
                                    "label": best_label,
                                    "prob": best_prob,
                                    "points": best_pts,
                                    "detections": overlay_detections,
                                    "is_ng": True,
                                    "side": current_side,
                                }
                        elif active_inspection:
                            locked_overlay = None

            with data_lock:
                if block_overlay:
                    latest_ai_results = default_ai_results(current_side)
                elif inspection_active and locked_overlay and locked_overlay.get("side") == current_side:
                    latest_ai_results = locked_overlay.copy()
                else:
                    latest_ai_results = {
                        "label": best_label,
                        "prob": best_prob,
                        "points": best_pts if master_ng_found else [],
                        "detections": overlay_detections if master_ng_found else [],
                        "is_ng": master_ng_found,
                        "side": current_side,
                    }
        except Exception as e: print(f"[AI] Error: {e}", flush=True)

# --- Stream & Camera ---
def build_camera_cmd():
    roi = ["0,0,1,1", "0.1,0.1,0.8,0.8", "0.2,0.2,0.6,0.6", "0.3,0.3,0.4,0.4"][current_zoom_index]
    with data_lock:
        lens_position = float(current_camera_lens_position)
    return [
        "rpicam-vid", "-t", "0", "--inline", "--codec", "mjpeg",
        "--width", "1920", "--height", "1080", "--framerate", "30",
        "--nopreview", "--autofocus-mode", "manual", "--lens-position", f"{lens_position:.2f}",
        "--roi", roi, "--quality", "85", "-o", "-"
    ]


def stop_camera_stream_process():
    global camera_stream_proc
    with camera_proc_lock:
        proc = camera_stream_proc
        camera_stream_proc = None

    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=1.5)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except Exception:
            pass


def update_camera_stream():
    global latest_frame, latest_raw_frame, camera_stream_proc
    while True:
        if not system_on or camera_pause_event.is_set():
            stop_camera_stream_process()
            time.sleep(0.2)
            continue
        proc = None
        try:
            proc = subprocess.Popen(build_camera_cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**6)
            with camera_proc_lock:
                camera_stream_proc = proc
            data = b""
            while system_on and not camera_pause_event.is_set():
                chunk = proc.stdout.read(8192)
                if not chunk: break
                data += chunk
                a = data.find(b"\xff\xd8"); b = data.find(b"\xff\xd9")
                if a != -1 and b != -1:
                    jpg = data[a : b + 2]; data = data[b + 2 :]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        with frame_lock: latest_raw_frame = frame; latest_frame = frame
                if proc.poll() is not None: break
            with camera_proc_lock:
                if camera_stream_proc is proc:
                    camera_stream_proc = None
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
        except Exception as e:
            with camera_proc_lock:
                if camera_stream_proc is proc:
                    camera_stream_proc = None
            print(f"[CAMERA] Stream error: {e}", flush=True)
            time.sleep(1)

def system_monitor_thread():
    while True:
        try:
            base_url, key = get_supabase_settings()
            url = f"{base_url}/rest/v1/system_status"
            headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            with data_lock:
                ai_res = latest_ai_results.copy()
            stats = get_pi_stats()
            printer = get_printer_status(force_refresh=False)
            all_ips = get_all_ips()
            nozzle_temp = _as_float(printer.get("nozzle_temp"), 0.0)
            bed_temp = _as_float(printer.get("bed_temp"), 0.0)
            base_payload = {
                "pi_cpu_usage": stats.get("cpu_usage"),
                "pi_ram_usage": stats.get("ram_usage"),
                "pi_disk_usage": stats.get("disk_usage"),
                "pi_cpu_temp": stats.get("cpu_temp"),
                "robot_status": get_robot_status(),
                "system_active": system_on,
                "printer_status": str(printer.get("status") or "Disconnected"),
                "printer_nozzle_temp": nozzle_temp,
                "printer_bed_temp": bed_temp,
                "server_ip": all_ips[0] if len(all_ips) > 0 else "127.0.0.1",
                "modbus_port": 5020,
                "timestamp": datetime.datetime.now(UTC).isoformat(),
            }

            extended_payload = {
                **base_payload,
                "printer_progress": _as_float(printer.get("percent"), 0.0),
                "printer_task_name": str(printer.get("task_name") or "").strip(),
                "printer_remaining_time": _as_int(printer.get("remaining_time"), 0),
                "printer_sub_stage": str(printer.get("sub_stage") or "").strip(),
            }

            response, removed_columns, sent_payload = post_json_pruning_unknown_columns(
                url,
                extended_payload,
                headers,
                timeout=(3.0, 10.0),
            )
            if response.status_code not in (200, 201):
                log_system_status_sync(f"status={response.status_code}, body={response.text[:240]}")
            else:
                removed_note = ""
                if removed_columns:
                    removed_note = f", removed={','.join(removed_columns)}"
                log_system_status_sync(
                    "ok "
                    f"printer_status={extended_payload['printer_status']}, "
                    f"progress={extended_payload['printer_progress']}, "
                    f"task={extended_payload['printer_task_name'] or '-'}"
                    f"{removed_note}, keys_sent={len(sent_payload)}"
                )
        except Exception as e:
            log_system_status_sync(f"exception: {e}")
        time.sleep(30)
register_routes(app, sys.modules[__name__])


def _handle_shutdown_signal(signum, _frame):
    try:
        send_pi_offline_alert_once()
    finally:
        raise SystemExit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    sync_total_parts_from_supabase()
    send_pi_online_alert_async()
    threading.Thread(target=update_camera_stream, daemon=True).start()
    threading.Thread(target=ai_inference_thread, daemon=True).start()
    threading.Thread(target=start_printer_mqtt_thread, daemon=True).start()
    threading.Thread(target=start_modbus_thread, daemon=True).start()
    threading.Thread(target=system_monitor_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

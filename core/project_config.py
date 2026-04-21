import json
import os


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_SUPABASE_URL = "https://ptxfbxwufbrivfrcplku.supabase.co"
DEFAULT_SUPABASE_KEY = ""
DEFAULT_CAPTURE_BUCKET = "inspection-captures"
DEFAULT_AI_MODEL_PATH = os.path.join(BASE_DIR, "best_openvino_model")
DEFAULT_AI_TASK = "obb"
DEFAULT_AI_IMGSZ = 640
DEFAULT_AI_BASE_CONF = 0.10
DEFAULT_CAMERA_LENS_POSITION = 6.0
DEFAULT_SIDE3_SCALE_MM_PER_PIXEL = 0.05
DEFAULT_SIDE3_PART_HEIGHT_MM = 25.0
DEFAULT_SIDE3_CAMERA_HEIGHT_MM = 300.0


def load_local_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_local_config(data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=True)


def has_printer_pairing_config(cfg=None):
    cfg = cfg if isinstance(cfg, dict) else load_local_config()
    return bool(str(cfg.get("ACCESS_CODE", "")).strip() and str(cfg.get("SERIAL_NO", "")).strip())


def get_supabase_settings():
    cfg = load_local_config()
    base_url = str(os.getenv("SUPABASE_URL") or cfg.get("SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    api_key = str(os.getenv("SUPABASE_KEY") or cfg.get("SUPABASE_KEY") or DEFAULT_SUPABASE_KEY).strip()
    return base_url, api_key


def get_capture_bucket():
    cfg = load_local_config()
    return str(os.getenv("SUPABASE_CAPTURE_BUCKET") or cfg.get("SUPABASE_CAPTURE_BUCKET") or DEFAULT_CAPTURE_BUCKET).strip()


def _resolve_local_path(path_value, default_path):
    raw_value = str(path_value or default_path).strip()
    if not raw_value:
        raw_value = str(default_path)
    if os.path.isabs(raw_value):
        return os.path.normpath(raw_value)
    return os.path.normpath(os.path.join(BASE_DIR, raw_value))


def _read_model_task_from_metadata(model_path):
    metadata_path = os.path.join(model_path, "metadata.yaml") if os.path.isdir(model_path) else None
    if not metadata_path or not os.path.exists(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("task:"):
                    return stripped.split(":", 1)[1].strip().strip("'\"").lower() or None
    except Exception:
        return None
    return None


def _as_int(value, default_value):
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else int(default_value)
    except (TypeError, ValueError):
        return int(default_value)


def _as_float(value, default_value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return float(default_value)


def get_ai_runtime_settings():
    cfg = load_local_config()
    model_path = _resolve_local_path(
        os.getenv("AI_MODEL_PATH") or cfg.get("AI_MODEL_PATH") or DEFAULT_AI_MODEL_PATH,
        DEFAULT_AI_MODEL_PATH,
    )
    inferred_task = _read_model_task_from_metadata(model_path)
    task = str(
        os.getenv("AI_MODEL_TASK")
        or cfg.get("AI_MODEL_TASK")
        or inferred_task
        or DEFAULT_AI_TASK
    ).strip().lower()
    return {
        "model_path": model_path,
        "task": task or DEFAULT_AI_TASK,
        "imgsz": _as_int(os.getenv("AI_IMGSZ") or cfg.get("AI_IMGSZ") or DEFAULT_AI_IMGSZ, DEFAULT_AI_IMGSZ),
        "base_conf": _as_float(
            os.getenv("AI_BASE_CONF") or cfg.get("AI_BASE_CONF") or DEFAULT_AI_BASE_CONF,
            DEFAULT_AI_BASE_CONF,
        ),
    }


def get_camera_focus_settings():
    cfg = load_local_config()
    raw_value = os.getenv("CAMERA_LENS_POSITION") or cfg.get("CAMERA_LENS_POSITION") or DEFAULT_CAMERA_LENS_POSITION
    try:
        lens_position = float(raw_value)
    except (TypeError, ValueError):
        lens_position = float(DEFAULT_CAMERA_LENS_POSITION)
    return {
        "lens_position": lens_position,
    }


def get_side3_measurement_settings():
    cfg = load_local_config()
    raw_scale = _as_float(
        os.getenv("SIDE3_SCALE_MM_PER_PIXEL") or cfg.get("SIDE3_SCALE_MM_PER_PIXEL") or DEFAULT_SIDE3_SCALE_MM_PER_PIXEL,
        DEFAULT_SIDE3_SCALE_MM_PER_PIXEL,
    )
    gagebox_height_mm = _as_float(
        os.getenv("SIDE3_GAGEBOX_HEIGHT_MM") or cfg.get("SIDE3_GAGEBOX_HEIGHT_MM") or 0.0,
        0.0,
    )
    part_height_mm = _as_float(
        os.getenv("SIDE3_PART_HEIGHT_MM") or cfg.get("SIDE3_PART_HEIGHT_MM") or DEFAULT_SIDE3_PART_HEIGHT_MM,
        DEFAULT_SIDE3_PART_HEIGHT_MM,
    )
    camera_height_mm = _as_float(
        os.getenv("SIDE3_CAMERA_HEIGHT_MM") or cfg.get("SIDE3_CAMERA_HEIGHT_MM") or DEFAULT_SIDE3_CAMERA_HEIGHT_MM,
        DEFAULT_SIDE3_CAMERA_HEIGHT_MM,
    )

    effective_scale = raw_scale
    if camera_height_mm > max(gagebox_height_mm, part_height_mm) and raw_scale > 0:
        distance_cal = max(1.0, camera_height_mm - gagebox_height_mm)
        distance_part = max(1.0, camera_height_mm - part_height_mm)
        effective_scale = raw_scale * (distance_part / distance_cal)
    return {
        "scale_mm_per_pixel": raw_scale,
        "effective_scale_mm_per_pixel": effective_scale,
        "gagebox_height_mm": gagebox_height_mm,
        "part_height_mm": part_height_mm,
        "camera_height_mm": camera_height_mm,
    }


def get_line_bot_settings():
    cfg = load_local_config()
    return {
        "channel_secret": str(os.getenv("LINE_CHANNEL_SECRET") or cfg.get("LINE_CHANNEL_SECRET") or "").strip(),
        "channel_access_token": str(
            os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or cfg.get("LINE_CHANNEL_ACCESS_TOKEN") or ""
        ).strip(),
        "target_user_id": str(os.getenv("LINE_TARGET_USER_ID") or cfg.get("LINE_TARGET_USER_ID") or "").strip(),
    }

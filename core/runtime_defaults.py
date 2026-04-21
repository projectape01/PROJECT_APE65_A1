def empty_printer_state(ip=None):
    return {
        "status": "Disconnected",
        "nozzle_temp": 0,
        "bed_temp": 0,
        "percent": 0,
        "task_name": "Unknown",
        "remaining_time": 0,
        "sub_stage": "N/A",
        "ip": ip,
        "last_updated": 0.0,
    }


def reset_part_session():
    return {
        "part_id": 0,
        "side1": None,
        "side2": None,
        "side3": None,
        "defect_s1": None,
        "defect_s2": None,
        "defect_s3": None,
        "capture_s1": None,
        "capture_s2": None,
        "capture_s3": None,
        "dimension_top": None,
        "dimension_bottom": None,
        "dimension_length": None,
        "dimension_status": None,
        "dimension_message": None,
        "current_side": 1,
    }


def default_ai_results(side=1):
    return {
        "label": "---",
        "prob": 0,
        "points": [],
        "detections": [],
        "is_ng": False,
        "side": side,
    }

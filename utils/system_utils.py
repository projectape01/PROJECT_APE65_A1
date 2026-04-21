import ipaddress
import socket


def is_valid_ipv4(ip):
    try:
        ipaddress.IPv4Address(str(ip).strip())
        return True
    except Exception:
        return False


def can_connect_tcp(ip, port, timeout=0.8):
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def as_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def normalize_stage(info, status_text, old_stage):
    layer_now = info.get("layer_num")
    layer_total = info.get("total_layer_num")
    if layer_now is not None and layer_total is not None:
        try:
            return f"Layer {as_int(layer_now)}/{as_int(layer_total)}"
        except Exception:
            pass
    if layer_now is not None:
        try:
            return f"Layer {as_int(layer_now)}"
        except Exception:
            pass

    for key in ("stg_cur_name", "stage_name", "sub_stage_name", "print_stage_name"):
        val = info.get(key)
        if val not in (None, "", "None"):
            return str(val)

    for key in ("stg_cur", "stg", "mc_print_stage", "print_stage"):
        val = info.get(key)
        if val is None:
            continue
        try:
            num_value = int(val)
            if num_value != 0:
                return str(num_value)
        except Exception:
            return str(val)

    if status_text in {"IDLE", "FINISH", "PAUSE", "FAILED"}:
        return status_text
    return old_stage or "N/A"

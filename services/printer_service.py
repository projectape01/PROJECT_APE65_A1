import json
import os
import ssl
import time

import paho.mqtt.client as mqtt


def reset_printer_finish_cleanup_timer(runtime):
    runtime._printer_post_finish_armed = False
    runtime._printer_post_finish_deadline_ts = 0.0
    runtime._printer_finish_signal_sent = False
    runtime._printer_finish_cleared = False


def update_printer_finish_cleanup_timer(runtime, status_text):
    status_upper = str(status_text or "").strip().upper()
    finish_states = {"FINISH", "COMPLETE", "COMPLETED"}
    active_states = {"RUNNING", "PRINTING", "PREPARE", "PREPARING", "PAUSE", "PAUSED"}

    if status_upper in finish_states:
        if runtime._printer_finish_cleared:
            return
        if not runtime._printer_post_finish_armed:
            runtime._printer_post_finish_armed = True
            runtime._printer_post_finish_deadline_ts = time.time() + 30.0
        if not runtime._printer_finish_signal_sent:
            runtime._printer_finish_signal_sent = True
            runtime.trigger_modbus_signal(0)
            should_auto_ready = False
            with runtime.data_lock:
                should_auto_ready = (
                    bool(runtime.system_on)
                    and not bool(runtime.inspection_active)
                )
            if should_auto_ready:
                runtime.start_inspection_session()
        return

    if status_upper in active_states:
        reset_printer_finish_cleanup_timer(runtime)


def apply_printer_finish_cleanup_unlocked(runtime):
    if (
        runtime._printer_post_finish_armed
        and runtime._printer_post_finish_deadline_ts > 0
        and time.time() >= runtime._printer_post_finish_deadline_ts
    ):
        runtime._printer_status_cache["value"]["status"] = "IDLE"
        runtime._printer_status_cache["value"]["percent"] = 0
        runtime._printer_status_cache["value"]["remaining_time"] = 0
        runtime._printer_status_cache["value"]["task_name"] = "Ready to Print"
        runtime._printer_status_cache["value"]["sub_stage"] = "-"
        runtime._printer_status_cache["value"]["last_updated"] = time.time()
        runtime._printer_status_cache["ts"] = time.time()
        runtime._printer_finish_cleared = True
        runtime._printer_post_finish_armed = False
        runtime._printer_post_finish_deadline_ts = 0.0
        runtime._printer_finish_signal_sent = True


def get_printer_status(runtime, force_refresh=False):
    if force_refresh:
        runtime._printer_reconnect_event.set()
    with runtime.data_lock:
        apply_printer_finish_cleanup_unlocked(runtime)
        state = runtime._printer_status_cache["value"].copy()
    state["pairing_configured"] = runtime.has_printer_pairing_config()
    last_updated = float(state.get("last_updated") or 0.0)
    if last_updated > 0 and (time.time() - last_updated) > 15:
        if state.get("status") not in {"Disconnected", "Conn Error", "Config Missing"}:
            state["status"] = "Stale"
    return state


def on_printer_connect(runtime, client, userdata, flags, rc, properties=None):
    reason_code = getattr(rc, "value", rc)
    serial_no = str((userdata or {}).get("serial", "")).strip()
    with runtime.data_lock:
        if reason_code == 0:
            runtime._printer_status_cache["value"]["status"] = "Connected"
            runtime._printer_status_cache["ts"] = time.time()
        else:
            runtime._printer_status_cache["value"]["status"] = f"Error {reason_code}"
            runtime._printer_status_cache["ts"] = time.time()
    if reason_code != 0 or not serial_no:
        return
    topic = f"device/{serial_no}/report"
    client.subscribe(topic)
    try:
        client.publish(
            f"device/{serial_no}/request",
            json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}),
            qos=0,
        )
    except Exception:
        pass


def on_printer_message(runtime, client, userdata, msg):
    try:
        packet = json.loads(msg.payload.decode("utf-8", errors="ignore"))
    except Exception:
        return
    info = packet.get("print")
    if not isinstance(info, dict):
        return

    with runtime.data_lock:
        state = runtime._printer_status_cache["value"]
        gcode_state = str(info.get("gcode_state") or state.get("status") or "Connected")
        if runtime._printer_finish_cleared and gcode_state.strip().upper() in {"FINISH", "COMPLETE", "COMPLETED"}:
            gcode_state = "IDLE"
        state["status"] = gcode_state if gcode_state else "Connected"
        if state["status"] == "Connecting":
            state["status"] = "Connected"
        update_printer_finish_cleanup_timer(runtime, state["status"])
        apply_printer_finish_cleanup_unlocked(runtime)

        if "nozzle_temper" in info:
            state["nozzle_temp"] = runtime._as_float(info.get("nozzle_temper"), state["nozzle_temp"])
        if "bed_temper" in info:
            state["bed_temp"] = runtime._as_float(info.get("bed_temper"), state["bed_temp"])
        if "mc_percent" in info:
            state["percent"] = max(0, min(100, runtime._as_float(info.get("mc_percent"), state["percent"])))
        if "mc_remaining_time" in info:
            state["remaining_time"] = max(0, runtime._as_int(info.get("mc_remaining_time"), state["remaining_time"]))

        task_name = (
            info.get("subtask_name")
            or info.get("gcode_file")
            or info.get("project_name")
            or state.get("task_name")
        )
        if task_name:
            state["task_name"] = str(task_name)

        state["sub_stage"] = runtime._normalize_stage(info, state["status"], state.get("sub_stage"))
        state["last_updated"] = time.time()
        runtime._printer_status_cache["ts"] = time.time()


def start_printer_mqtt_thread(runtime):
    while True:
        cfg = runtime.load_local_config()
        printer_ip = str(cfg.get("PRINTER_IP", "")).strip()
        access_code = str(cfg.get("ACCESS_CODE", "")).strip()
        serial_no = str(cfg.get("SERIAL_NO", "")).strip()

        if not (runtime.is_valid_ipv4(printer_ip) and access_code and serial_no):
            with runtime.data_lock:
                runtime._printer_status_cache["value"] = runtime._empty_printer_state(printer_ip or None)
                runtime._printer_status_cache["value"]["status"] = "Config Missing"
                runtime._printer_status_cache["value"]["task_name"] = "Set Printer Config"
                runtime._printer_status_cache["ts"] = time.time()
            time.sleep(2)
            continue

        client_id = f"test01-{os.getpid()}-{int(time.time()) % 100000}"
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        client.user_data_set({"serial": serial_no})
        client.username_pw_set("bblp", access_code)
        client.on_connect = lambda c, u, f, r, p=None: on_printer_connect(runtime, c, u, f, r, p)
        client.on_message = lambda c, u, m: on_printer_message(runtime, c, u, m)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)

        with runtime.data_lock:
            runtime._printer_status_cache["value"]["ip"] = printer_ip
            runtime._printer_status_cache["value"]["status"] = "Connecting"
            runtime._printer_status_cache["value"]["task_name"] = "Connecting..."
            runtime._printer_status_cache["ts"] = time.time()
        runtime._printer_mqtt_client = client

        try:
            client.connect(printer_ip, 8883, 60)
            client.loop_start()
            last_push_ts = 0.0
            connect_deadline = time.time() + 8.0
            connected_once = False
            while True:
                if runtime._printer_reconnect_event.is_set():
                    runtime._printer_reconnect_event.clear()
                    break
                if client.is_connected():
                    connected_once = True
                elif not connected_once and time.time() < connect_deadline:
                    time.sleep(0.2)
                    continue
                else:
                    break
                now = time.time()
                if now - last_push_ts >= 5.0:
                    try:
                        client.publish(
                            f"device/{serial_no}/request",
                            json.dumps({"pushing": {"sequence_id": str(int(now)), "command": "pushall"}}),
                            qos=0,
                        )
                    except Exception:
                        pass
                    last_push_ts = now
                time.sleep(1)
        except Exception as e:
            with runtime.data_lock:
                runtime._printer_status_cache["value"]["status"] = "Conn Error"
                runtime._printer_status_cache["value"]["task_name"] = "Printer Offline"
                runtime._printer_status_cache["ts"] = time.time()
            print(f"[MQTT] Error in thread: {e}", flush=True)
            if runtime._printer_reconnect_event.is_set():
                runtime._printer_reconnect_event.clear()
            time.sleep(2)
        finally:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass
            runtime._printer_mqtt_client = None

import datetime
import hashlib
import hmac
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

import cv2
from flask import Response, jsonify, render_template, request


def register_routes(app, runtime):
    roi_presets = ["0,0,1,1", "0.1,0.1,0.8,0.8", "0.2,0.2,0.6,0.6", "0.3,0.3,0.4,0.4"]

    def get_camera_focus_payload():
        return runtime.get_camera_focus_payload()

    def make_json_safe_ai_results(ai_res):
        payload = dict(ai_res or {})
        side3_measurement = payload.get("side3_measurement")
        if isinstance(side3_measurement, dict):
            cleaned = {}
            for key, value in side3_measurement.items():
                if key == "contour":
                    continue
                if hasattr(value, "tolist"):
                    cleaned[key] = value.tolist()
                else:
                    cleaned[key] = value
            payload["side3_measurement"] = cleaned
        return payload

    def get_line_settings():
        return runtime.get_line_bot_settings()

    def is_timestamp_fresh(timestamp_value, stale_seconds=180):
        raw_value = str(timestamp_value or "").strip()
        if not raw_value:
            return False
        try:
            normalized = raw_value.replace("Z", "+00:00")
            parsed = datetime.datetime.fromisoformat(normalized)
        except Exception:
            return False
        if parsed.tzinfo is None:
            current = datetime.datetime.now()
        else:
            current = datetime.datetime.now(parsed.tzinfo)
        return abs((current - parsed).total_seconds()) <= float(stale_seconds)

    def verify_line_signature(raw_body, signature):
        settings = get_line_settings()
        secret = settings.get("channel_secret") or ""
        if not secret:
            return False
        digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        expected = __import__("base64").b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, str(signature or ""))

    def push_line_text_message(text):
        settings = get_line_settings()
        access_token = str(settings.get("channel_access_token") or "").strip()
        target_user_id = str(settings.get("target_user_id") or "").strip()
        if not access_token:
            raise ValueError("LINE channel access token is not configured.")
        if not target_user_id:
            raise ValueError("LINE target user ID is not configured.")

        payload = {
            "to": target_user_id,
            "messages": [
                {
                    "type": "text",
                    "text": str(text or "").strip() or "APE65 A1 test message",
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                response_body = resp.read().decode("utf-8", errors="replace")
                return resp.status, response_body
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LINE push failed: HTTP {exc.code} {response_body}") from exc

    def push_line_image_message(image_url):
        settings = get_line_settings()
        access_token = str(settings.get("channel_access_token") or "").strip()
        target_user_id = str(settings.get("target_user_id") or "").strip()
        if not access_token:
            raise ValueError("LINE channel access token is not configured.")
        if not target_user_id:
            raise ValueError("LINE target user ID is not configured.")
        image_url = str(image_url or "").strip()
        if not image_url:
            raise ValueError("LINE image URL is empty.")

        payload = {
            "to": target_user_id,
            "messages": [
                {
                    "type": "image",
                    "originalContentUrl": image_url,
                    "previewImageUrl": image_url,
                }
            ],
        }
        return _line_api_request("https://api.line.me/v2/bot/message/push", payload)

    def _line_api_request(endpoint, payload):
        settings = get_line_settings()
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

    def reply_line_text_message(reply_token, text):
        if not reply_token:
            raise ValueError("LINE reply token is missing.")
        return _line_api_request(
            "https://api.line.me/v2/bot/message/reply",
            {
                "replyToken": str(reply_token),
                "messages": [
                    {
                        "type": "text",
                        "text": str(text or "").strip() or "APE65 A1",
                    }
                ],
            },
        )

    def reply_line_flex_message(reply_token, alt_text, contents):
        if not reply_token:
            raise ValueError("LINE reply token is missing.")
        return _line_api_request(
            "https://api.line.me/v2/bot/message/reply",
            {
                "replyToken": str(reply_token),
                "messages": [
                    {
                        "type": "flex",
                        "altText": str(alt_text or "APE65 A1"),
                        "contents": contents,
                    }
                ],
            },
        )

    def reply_line_messages(reply_token, messages):
        if not reply_token:
            raise ValueError("LINE reply token is missing.")
        normalized_messages = [msg for msg in (messages or []) if isinstance(msg, dict)]
        if not normalized_messages:
            raise ValueError("LINE messages payload is empty.")
        return _line_api_request(
            "https://api.line.me/v2/bot/message/reply",
            {
                "replyToken": str(reply_token),
                "messages": normalized_messages,
            },
        )

    def build_status_snapshot():
        printer = runtime.get_printer_status(force_refresh=False)
        printer_status = str(printer.get("status") or "Disconnected").upper()
        robot_status = str(runtime.get_robot_status() or "Disconnected").upper()
        base_url, key = runtime.get_supabase_settings()
        latest_system_status = {}

        bambu_online = printer_status not in {"DISCONNECTED", "UNKNOWN", ""} and not printer_status.startswith("CONN ERROR")
        bambu_status = "ONLINE" if bambu_online else "OFFLINE"
        cobot_status = "ONLINE" if robot_status == "CONNECTED" else "OFFLINE"

        database_status = "OFFLINE"
        try:
            test_url = f"{base_url}/rest/v1/system_status?select=timestamp,printer_status,robot_status&order=timestamp.desc&limit=1"
            headers = {"apikey": key, "Authorization": f"Bearer {key}"}
            response = runtime.get_json_with_retry(test_url, headers, timeout=(3.0, 10.0))
            if getattr(response, "status_code", None) == 200:
                database_status = "ONLINE"
                parsed = response.json()
                if isinstance(parsed, list) and parsed:
                    latest_system_status = parsed[0] if isinstance(parsed[0], dict) else {}
        except Exception:
            database_status = "OFFLINE"

        pi_fresh = is_timestamp_fresh(latest_system_status.get("timestamp"), 180)
        pi_status = "ONLINE" if (pi_fresh or database_status == "ONLINE") else "ONLINE"
        if latest_system_status:
            printer_status = str(latest_system_status.get("printer_status") or printer_status).upper()
            robot_status = str(latest_system_status.get("robot_status") or robot_status).upper()
            bambu_online = printer_status not in {"DISCONNECTED", "UNKNOWN", ""} and not printer_status.startswith("CONN ERROR")
            bambu_status = "ONLINE" if bambu_online else "OFFLINE"
            cobot_status = "ONLINE" if robot_status == "CONNECTED" else "OFFLINE"

        overall_status = "ONLINE" if all(
            status == "ONLINE" for status in (pi_status, bambu_status, cobot_status, database_status)
        ) else "SYSTEM NOT READY"
        return {
            "pi_status": pi_status,
            "bambu_status": bambu_status,
            "cobot_status": cobot_status,
            "database_status": database_status,
            "overall_status": overall_status,
        }

    def build_status_flex_message():
        snapshot = build_status_snapshot()
        overall_online = snapshot["overall_status"] == "ONLINE"
        accent_color = "#10B981" if overall_online else "#F59E0B"
        overall_text_size = "xxl" if len(snapshot["overall_status"]) <= 10 else "xl"

        def status_row(label, value):
            value_color = "#10B981" if value == "ONLINE" else "#EF4444" if value == "OFFLINE" else "#F59E0B"
            return {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": label,
                        "size": "sm",
                        "color": "#94A3B8",
                        "flex": 5,
                    },
                    {
                        "type": "text",
                        "text": value,
                        "size": "sm",
                        "weight": "bold",
                        "align": "end",
                        "color": value_color,
                        "flex": 3,
                    },
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
                    {
                        "type": "text",
                        "text": "APE65 A1 STATUS",
                        "size": "xs",
                        "color": "#CBD5E1",
                        "weight": "bold",
                    },
                    {
                        "type": "text",
                        "text": snapshot["overall_status"],
                        "margin": "md",
                        "size": overall_text_size,
                        "weight": "bold",
                        "color": accent_color,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": "Current system health overview",
                        "margin": "sm",
                        "size": "sm",
                        "color": "#94A3B8",
                        "wrap": True,
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    status_row("Raspberry Pi", snapshot["pi_status"]),
                    status_row("Bambu Lab A1", snapshot["bambu_status"]),
                    status_row("TM Cobot", snapshot["cobot_status"]),
                    status_row("Database", snapshot["database_status"]),
                ],
            },
        }

    def build_status_text():
        snapshot = build_status_snapshot()
        lines = [
            "APE65 A1 STATUS",
            f"Raspberry Pi: {snapshot['pi_status']}",
            f"Bambu Lab A1: {snapshot['bambu_status']}",
            f"TM Cobot: {snapshot['cobot_status']}",
            f"Database: {snapshot['database_status']}",
            f"Overall System Status: {snapshot['overall_status']}",
        ]
        return "\n".join(lines)

    def fetch_today_summary():
        local_now = datetime.datetime.now()
        start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_iso = start_of_day.strftime("%Y-%m-%d %H:%M:%S")

        base_url, key = runtime.get_supabase_settings()
        select = urllib.parse.quote("part_id,result,side1,side2,side3,record_timestamp", safe=",")
        timestamp_filter = urllib.parse.quote(f"gte.{start_iso}", safe=":.")
        url = (
            f"{base_url}/rest/v1/part_records"
            f"?select={select}"
            f"&record_timestamp={timestamp_filter}"
            f"&order=part_id.asc"
        )
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}

        response = runtime.get_json_with_retry(url, headers, timeout=(3.0, 10.0))
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

        ng_side_counter = Counter()
        for row in rows:
            if str(row.get("result") or "").upper() != "NG":
                continue
            for side_name in ("side1", "side2", "side3"):
                side_value = str(row.get(side_name) or "").upper()
                if side_value.startswith("NG_"):
                    ng_side_counter.update([side_name.replace("side", "SIDE ")])

        top_ng_side = ng_side_counter.most_common(1)[0][0] if ng_side_counter else "-"
        yield_pct = (good / total * 100.0) if total > 0 else 0.0
        return {
            "total": total,
            "good": good,
            "ng": ng,
            "yield_pct": yield_pct,
            "top_ng_side": top_ng_side,
        }

    def build_summary_text():
        summary = fetch_today_summary()
        return "\n".join([
            "APE65 A1 SUMMARY",
            f"Total: {summary['total']}",
            f"GOOD: {summary['good']}",
            f"NG: {summary['ng']}",
            f"Yield: {summary['yield_pct']:.2f}%",
            f"Top NG Side: {summary['top_ng_side']}",
        ])

    def build_summary_flex_message():
        summary = fetch_today_summary()
        total = int(summary["total"] or 0)
        good = int(summary["good"] or 0)
        ng = int(summary["ng"] or 0)
        yield_pct = float(summary["yield_pct"] or 0.0)
        top_ng_side = str(summary["top_ng_side"] or "-")

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
                    {
                        "type": "text",
                        "text": label,
                        "size": "xs",
                        "color": "#94A3B8",
                        "weight": "bold",
                    },
                    {
                        "type": "text",
                        "text": value,
                        "size": "xl",
                        "weight": "bold",
                        "color": color,
                    },
                ],
            }

        def summary_row(label, value, color="#E2E8F0"):
            return {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": label,
                        "size": "sm",
                        "color": "#94A3B8",
                        "flex": 5,
                    },
                    {
                        "type": "text",
                        "text": value,
                        "size": "sm",
                        "weight": "bold",
                        "align": "end",
                        "color": color,
                        "flex": 3,
                        "wrap": True,
                    },
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
                    {
                        "type": "text",
                        "text": "APE65 A1 SUMMARY",
                        "size": "xs",
                        "color": "#CBD5E1",
                        "weight": "bold",
                    },
                    {
                        "type": "text",
                        "text": f"{yield_pct:.2f}%",
                        "margin": "md",
                        "size": "xxl",
                        "weight": "bold",
                        "color": accent_color,
                    },
                    {
                        "type": "text",
                        "text": "Current production summary",
                        "margin": "sm",
                        "size": "sm",
                        "color": "#94A3B8",
                        "wrap": True,
                    },
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
                    {
                        "type": "separator",
                        "margin": "md",
                    },
                ],
            },
        }

    def fetch_latest_part_record():
        base_url, key = runtime.get_supabase_settings()
        select = urllib.parse.quote(
            "part_id,result,side1,side2,side3,record_timestamp,defect _s1,defect _s2,defect _s3,dimension of top,dimension of bottom,dimension of length,capture_s1,capture_s2,capture_s3",
            safe=", _",
        )
        url = (
            f"{base_url}/rest/v1/part_records"
            f"?select={select}"
            f"&order=part_id.desc"
            f"&limit=1"
        )
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}

        response = runtime.get_json_with_retry(url, headers, timeout=(3.0, 10.0))
        try:
            if getattr(response, "status_code", None) == 200:
                parsed = response.json()
                if isinstance(parsed, list) and parsed:
                    return parsed[0]
        except Exception:
            pass
        return None

    def fetch_part_record_by_id(part_id):
        try:
            part_id = int(part_id)
        except (TypeError, ValueError):
            return None
        if part_id <= 0:
            return None

        base_url, key = runtime.get_supabase_settings()
        select = urllib.parse.quote(
            "part_id,result,side1,side2,side3,record_timestamp,defect _s1,defect _s2,defect _s3,dimension of top,dimension of bottom,dimension of length,capture_s1,capture_s2,capture_s3",
            safe=", _",
        )
        part_filter = urllib.parse.quote(f"eq.{part_id}", safe=".")
        url = (
            f"{base_url}/rest/v1/part_records"
            f"?select={select}"
            f"&part_id={part_filter}"
            f"&limit=1"
        )
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}

        response = runtime.get_json_with_retry(url, headers, timeout=(3.0, 10.0))
        try:
            if getattr(response, "status_code", None) == 200:
                parsed = response.json()
                if isinstance(parsed, list) and parsed:
                    return parsed[0]
        except Exception:
            pass
        return None

    def get_latest_capture_urls(latest):
        if not isinstance(latest, dict):
            return {}
        urls = {}
        for key in ("capture_s1", "capture_s2", "capture_s3"):
            value = str(latest.get(key) or "").strip()
            if value.lower().startswith("http://") or value.lower().startswith("https://"):
                urls[key] = value
        return urls

    def build_now_text(latest=None):
        latest = latest if isinstance(latest, dict) else fetch_latest_part_record()
        if not latest:
            return "APE65 A1 NOW\nNo inspection record found."

        return "\n".join([
            "APE65 A1 NOW",
            f"Part ID: {latest.get('part_id')}",
            f"Result: {str(latest.get('result') or '-').upper()}",
            f"Side 1: {latest.get('side1') or '-'}",
            f"Side 2: {latest.get('side2') or '-'}",
            f"Side 3: {latest.get('side3') or '-'}",
            f"Time: {latest.get('record_timestamp') or '-'}",
        ])

    def build_now_flex_message(latest=None, title_text="APE65 A1 NOW", subtitle_text="Latest inspection record"):
        latest = latest if isinstance(latest, dict) else fetch_latest_part_record()
        if not latest:
            return {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "paddingAll": "20px",
                    "contents": [
                        {"type": "text", "text": "APE65 A1 NOW", "weight": "bold", "size": "lg"},
                        {"type": "text", "text": "No inspection record found.", "margin": "md", "color": "#94A3B8"},
                    ],
                },
            }

        result_text = str(latest.get("result") or "-").upper()
        result_color = "#10B981" if result_text == "GOOD" else "#EF4444" if result_text == "NG" else "#E2E8F0"
        header_bg_color = "#14532D" if result_text == "GOOD" else "#7F1D1D" if result_text == "NG" else "#0F172A"
        header_sub_color = "#BBF7D0" if result_text == "GOOD" else "#FECACA" if result_text == "NG" else "#CBD5E1"
        header_hint_color = "#86EFAC" if result_text == "GOOD" else "#FCA5A5" if result_text == "NG" else "#94A3B8"
        recorded_at_raw = str(latest.get("record_timestamp") or "").strip()
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
        dimension_top = latest.get("dimension of top")
        dimension_bottom = latest.get("dimension of bottom")
        dimension_length = latest.get("dimension of length")
        has_dimensions = any(v is not None for v in (dimension_top, dimension_bottom, dimension_length))
        dim_targets = {
            "TOP": 19.50,
            "BOTTOM": 24.50,
            "LENGTH": 90.00,
        }
        dim_tolerance = 0.3

        def row(label, value, color="#E2E8F0"):
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
            row("Part ID", latest.get("part_id") or "-", "#0F172A"),
            row("Result", result_text, result_color),
            row(
                "Side 1",
                latest.get("side1") or "-",
                "#EF4444" if str(latest.get("side1") or "").upper().startswith("NG") else "#0F172A",
            ),
            row(
                "Side 2",
                latest.get("side2") or "-",
                "#EF4444" if str(latest.get("side2") or "").upper().startswith("NG") else "#0F172A",
            ),
            row(
                "Side 3",
                latest.get("side3") or "-",
                "#EF4444" if str(latest.get("side3") or "").upper().startswith("NG") else "#0F172A",
            ),
        ]

        defect_map = [
            ("Defect S1", latest.get("defect _s1") or "-"),
            ("Defect S2", latest.get("defect _s2") or "-"),
            ("Defect S3", latest.get("defect _s3") or "-"),
        ]
        if any(value not in ("", "-", None) for _label, value in defect_map):
            body_contents.append({"type": "separator", "margin": "md"})
            for label, value in defect_map:
                normalized = str(value or "-").strip()
                defect_color = "#EF4444" if normalized not in ("", "-") else "#0F172A"
                body_contents.append(row(label, normalized, defect_color))

        if has_dimensions:
            body_contents.append({"type": "separator", "margin": "md"})
            top_color = "#0F172A"
            bottom_color = "#0F172A"
            length_color = "#0F172A"
            try:
                if dimension_top is not None and abs(float(dimension_top) - dim_targets["TOP"]) > dim_tolerance:
                    top_color = "#EF4444"
            except Exception:
                pass
            try:
                if dimension_bottom is not None and abs(float(dimension_bottom) - dim_targets["BOTTOM"]) > dim_tolerance:
                    bottom_color = "#EF4444"
            except Exception:
                pass
            try:
                if dimension_length is not None and abs(float(dimension_length) - dim_targets["LENGTH"]) > dim_tolerance:
                    length_color = "#EF4444"
            except Exception:
                pass
            body_contents.extend([
                row("TOP", f"{float(dimension_top):.2f} mm" if dimension_top is not None else "-", top_color),
                row("BOTTOM", f"{float(dimension_bottom):.2f} mm" if dimension_bottom is not None else "-", bottom_color),
                row("LENGTH", f"{float(dimension_length):.2f} mm" if dimension_length is not None else "-", length_color),
            ])

        body_contents.append({"type": "separator", "margin": "md"})
        body_contents.append(row("Recorded Date", recorded_date or "-", "#0F172A"))
        body_contents.append(row("Recorded Time", recorded_time or "-", "#0F172A"))

        capture_urls = get_latest_capture_urls(latest)
        footer_contents = []
        side_buttons = [
            ("Side 1", capture_urls.get("capture_s1")),
            ("Side 2", capture_urls.get("capture_s2")),
            ("Side 3", capture_urls.get("capture_s3")),
        ]
        for label, url in side_buttons:
            if not url:
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
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": header_bg_color,
                "paddingAll": "20px",
                "contents": [
                    {"type": "text", "text": str(title_text), "size": "xs", "color": header_sub_color, "weight": "bold"},
                    {"type": "text", "text": f"PART {latest.get('part_id') or '-'}", "margin": "md", "size": "xxl", "weight": "bold", "color": "#FFFFFF"},
                    {"type": "text", "text": str(subtitle_text), "margin": "sm", "size": "sm", "color": header_hint_color, "wrap": True},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": body_contents,
            },
        }
        if footer_contents:
            bubble["footer"] = {
                "type": "box",
                "layout": "horizontal",
                "spacing": "xs",
                "paddingTop": "8px",
                "paddingBottom": "16px",
                "paddingStart": "20px",
                "paddingEnd": "20px",
                "contents": footer_contents,
            }
        return bubble

    def build_part_not_found_flex_message(part_id):
        return {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#334155",
                "paddingAll": "20px",
                "contents": [
                    {"type": "text", "text": "APE65 A1 PART SEARCH", "size": "xs", "color": "#CBD5E1", "weight": "bold"},
                    {"type": "text", "text": f"PART {part_id}", "margin": "md", "size": "xxl", "weight": "bold", "color": "#FFFFFF"},
                    {"type": "text", "text": "Inspection record not found", "margin": "sm", "size": "sm", "color": "#CBD5E1", "wrap": True},
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
                        "layout": "vertical",
                        "paddingAll": "14px",
                        "backgroundColor": "#F8FAFC",
                        "cornerRadius": "12px",
                        "contents": [
                            {"type": "text", "text": "No data available", "size": "lg", "weight": "bold", "color": "#0F172A"},
                            {"type": "text", "text": "Please check the Part ID and try again.", "margin": "sm", "size": "sm", "color": "#64748B", "wrap": True},
                        ],
                    },
                ],
            },
        }

    def maybe_handle_line_text_command(event):
        if str(event.get("type") or "").lower() != "message":
            return
        message = event.get("message") or {}
        if str(message.get("type") or "").lower() != "text":
            return

        incoming_text = str(message.get("text") or "").strip().lower()
        reply_token = str(event.get("replyToken") or "").strip()
        if not reply_token:
            return

        if incoming_text.startswith("part "):
            suffix = incoming_text[5:].strip()
            if suffix.isdigit():
                requested_part_id = int(suffix)
                record = fetch_part_record_by_id(requested_part_id)
                if not record:
                    reply_line_flex_message(
                        reply_token,
                        f"APE65 A1 PART {requested_part_id} not found",
                        build_part_not_found_flex_message(requested_part_id),
                    )
                    return
                reply_line_flex_message(
                    reply_token,
                    f"APE65 A1 PART {requested_part_id}",
                    build_now_flex_message(
                        record,
                        title_text="APE65 A1 PART",
                        subtitle_text=f"Inspection record for PART {requested_part_id}",
                    ),
                )
                return

        if incoming_text == "status":
            reply_line_flex_message(reply_token, build_status_text(), build_status_flex_message())
        elif incoming_text == "summary":
            reply_line_flex_message(reply_token, build_summary_text(), build_summary_flex_message())
        elif incoming_text == "now":
            reply_line_flex_message(reply_token, build_now_text(), build_now_flex_message())

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/line/webhook", methods=["GET", "POST", "HEAD", "OPTIONS"])
    @app.route("/line/webhook/", methods=["GET", "POST", "HEAD", "OPTIONS"])
    def line_webhook():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return jsonify({"success": True, "message": "LINE webhook endpoint ready"})

        raw_body = request.get_data() or b""
        signature = request.headers.get("X-Line-Signature", "")
        settings = get_line_settings()
        if settings.get("channel_secret") and not verify_line_signature(raw_body, signature):
            return jsonify({"success": False, "message": "Invalid signature"}), 403

        payload = request.get_json(silent=True) or {}
        events = payload.get("events") or []
        captured_user_ids = []
        for event in events:
            source = event.get("source") or {}
            user_id = str(source.get("userId") or "").strip()
            if not user_id:
                user_id = ""
            if user_id:
                captured_user_ids.append(user_id)
                try:
                    cfg = runtime.load_local_config()
                    current_target_user_id = str(cfg.get("LINE_TARGET_USER_ID") or "").strip()
                    if not current_target_user_id:
                        cfg["LINE_TARGET_USER_ID"] = user_id
                        runtime.save_local_config(cfg)
                except Exception as exc:
                    runtime.log_system_status_sync(f"LINE target user save failed: {exc}")
            try:
                maybe_handle_line_text_command(event)
            except Exception as exc:
                runtime.log_system_status_sync(f"LINE command handling failed: {exc}")

        runtime.log_system_status_sync(f"LINE webhook received {len(events)} event(s)")
        if captured_user_ids:
            runtime.log_system_status_sync(f"LINE target user captured: {captured_user_ids[-1]}")
        return jsonify({"success": True})

    @app.route("/api/line/status")
    def api_line_status():
        settings = get_line_settings()
        return jsonify({
            "success": True,
            "line_configured": bool(settings.get("channel_secret") and settings.get("channel_access_token")),
            "has_channel_secret": bool(settings.get("channel_secret")),
            "has_channel_access_token": bool(settings.get("channel_access_token")),
            "has_target_user_id": bool(settings.get("target_user_id")),
        })

    @app.route("/api/line/test_send", methods=["POST"])
    def api_line_test_send():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text") or "APE65 A1 test message"
        try:
            status_code, response_body = push_line_text_message(text)
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500
        return jsonify({
            "success": True,
            "status_code": int(status_code),
            "response": response_body,
        })

    @app.route("/api/line/test_daily_summary", methods=["POST"])
    def api_line_test_daily_summary():
        try:
            summary = runtime.fetch_today_line_summary()
            reason_label = "Test daily summary"
            status_code, response_body = runtime._push_line_flex(
                f"APE65 A1 DAILY SUMMARY {summary.get('date') or ''}".strip(),
                runtime._build_daily_summary_flex(summary, reason_label),
            )
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500
        return jsonify({
            "success": True,
            "status_code": int(status_code),
            "response": response_body,
            "summary": summary,
        })

    @app.route("/toggle_system", methods=["POST"])
    def toggle_system():
        with runtime.data_lock:
            runtime.system_on = not runtime.system_on
            if not runtime.system_on:
                runtime.inspection_active = False
                runtime.part_session = runtime.reset_part_session()
                runtime.locked_overlay = None
                runtime.latest_ai_results = runtime.default_ai_results(1)
                runtime.overlay_block_until = 0.0
            else:
                runtime.latest_ai_results = runtime.default_ai_results(
                    runtime.part_session.get("current_side", 1)
                )

        if not runtime.system_on:
            with runtime.frame_lock:
                runtime.latest_frame = None
                runtime.latest_raw_frame = None

        return jsonify({"success": True, "system_on": runtime.system_on})

    @app.route("/video_feed")
    def video_feed():
        def gen():
            last_t = 0
            while True:
                if time.time() - last_t < runtime.STREAM_INTERVAL_SEC:
                    time.sleep(0.01)
                    continue
                with runtime.frame_lock:
                    if runtime.latest_frame is None:
                        time.sleep(0.1)
                        continue
                    view = runtime.latest_frame.copy()
                with runtime.data_lock:
                    res = runtime.latest_ai_results.copy()
                view = runtime.render_overlay_frame(view, res)

                _, buf = cv2.imencode(".jpg", view, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                last_t = time.time()
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")

        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/video_feed_raw")
    def video_feed_raw():
        def gen():
            last_t = 0
            while True:
                if time.time() - last_t < runtime.STREAM_INTERVAL_SEC:
                    time.sleep(0.01)
                    continue
                with runtime.frame_lock:
                    if runtime.latest_frame is None:
                        time.sleep(0.1)
                        continue
                    view = runtime.latest_frame.copy()

                _, buf = cv2.imencode(".jpg", view, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                last_t = time.time()
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")

        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/api/capture", methods=["POST"])
    def api_capture():
        payload = request.get_json(silent=True) or {}
        folder = runtime.sanitize_capture_name(payload.get("folder") or "manual")
        frame = runtime.get_rendered_frame_snapshot()
        if frame is None:
            return jsonify({"success": False, "message": "No frame available."}), 503

        captured_at_dt = datetime.datetime.now()
        filename = f"{folder}_{captured_at_dt.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        local_dir = os.path.join(runtime.CAPTURES_DIR, folder)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            return jsonify({"success": False, "message": "Encode failed."}), 500
        with open(local_path, "wb") as fh:
            fh.write(buf.tobytes())

        return jsonify({
            "success": True,
            "filename": filename,
            "path": local_path,
        })

    @app.route("/api/capture/burst", methods=["POST"])
    def api_capture_burst():
        payload = request.get_json(silent=True) or {}
        folder = runtime.sanitize_capture_name(payload.get("folder") or "dataset")

        try:
            count = int(payload.get("count", 10))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Invalid image count."}), 400

        try:
            delay = float(payload.get("delay", 0.3))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Invalid interval."}), 400

        count = max(1, min(count, 500))
        delay = max(0.05, min(delay, 10.0))

        local_dir = os.path.join(runtime.CAPTURES_DIR, folder)
        os.makedirs(local_dir, exist_ok=True)

        saved_files = []
        runtime.camera_pause_event.set()
        runtime.stop_camera_stream_process()
        time.sleep(0.25)

        try:
            zoom_index = int(getattr(runtime, "current_zoom_index", 0) or 0)
            if zoom_index < 0 or zoom_index >= len(roi_presets):
                zoom_index = 0
            roi = roi_presets[zoom_index]

            for idx in range(count):
                captured_at_dt = datetime.datetime.now()
                filename = f"{folder}_{captured_at_dt.strftime('%Y%m%d_%H%M%S_%f')}_{idx + 1:03d}.jpg"
                local_path = os.path.join(local_dir, filename)
                cmd = [
                    "rpicam-jpeg",
                    "-n",
                    "-t",
                    "120",
                    "--width",
                    "2560",
                    "--height",
                    "1440",
                    "--quality",
                    "95",
                    "--autofocus-mode",
                    "manual",
                    "--lens-position",
                    f"{float(runtime.get_camera_focus_payload().get('lens_position') or 6.0):.2f}",
                    "--roi",
                    roi,
                    "-o",
                    local_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                if result.returncode != 0:
                    message = (result.stderr or result.stdout or "High-resolution capture failed.").strip()
                    if saved_files:
                        break
                    return jsonify({"success": False, "message": message}), 500

                if not os.path.exists(local_path):
                    if saved_files:
                        break
                    return jsonify({"success": False, "message": "Capture file was not created."}), 500

                saved_files.append(filename)
                if idx < count - 1:
                    time.sleep(delay)
        finally:
            runtime.camera_pause_event.clear()

        return jsonify({
            "success": True,
            "folder": folder,
            "count": len(saved_files),
            "files": saved_files,
            "path": local_dir,
        })

    @app.route("/get_status")
    def get_status():
        with runtime.data_lock:
            hist = runtime.inspection_history[-15:]
            ai_res = make_json_safe_ai_results(runtime.latest_ai_results.copy())
            recent_modbus_log = runtime.modbus_log[-15:]
        all_ips = runtime.get_all_ips()
        return jsonify({
            "system_on": runtime.system_on,
            "total_parts_inspected": runtime.total_parts_inspected,
            "inspection_history": hist,
            "ai_results": ai_res,
            "current_dimensions": runtime.get_dimension_payload_unlocked(),
            "inspection_state": {
                "part_id": runtime.part_session.get("part_id"),
                "current_side": runtime.part_session.get("current_side"),
                "inspection_active": runtime.inspection_active,
                "side1": runtime.part_session.get("side1"),
                "side2": runtime.part_session.get("side2"),
                "side3": runtime.part_session.get("side3"),
            },
            "printer": runtime.get_printer_status(force_refresh=False),
            "modbus_log": recent_modbus_log,
            "server_ip": all_ips[0] if len(all_ips) > 0 else "127.0.0.1",
            "backup_ip": all_ips[1] if len(all_ips) > 1 else None,
            "modbus_port": 5020,
            "robot_status": runtime.get_robot_status(),
            "pi_stats": runtime.get_pi_stats(),
            "camera_focus": get_camera_focus_payload(),
        })

    @app.route("/api/camera/focus", methods=["POST"])
    def api_camera_focus_save():
        payload = request.get_json(silent=True) or {}
        try:
            lens_position = runtime.set_camera_lens_position(payload.get("lens_position"))
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400

        runtime.stop_camera_stream_process()
        return jsonify({
            "success": True,
            "message": f"Lens position applied: {lens_position:.2f}",
            "camera_focus": get_camera_focus_payload(),
        })

    @app.route("/api/modbus/trigger", methods=["POST"])
    def api_modbus_trigger():
        payload = request.get_json(silent=True) or {}
        addr = int(payload.get("addr", payload.get("address", 0)))
        if addr < 0:
            return jsonify({"success": False, "message": "Invalid address."}), 400
        runtime.trigger_modbus_signal(addr)
        return jsonify({"success": True, "address": addr})

    @app.route("/api/printer/config", methods=["POST"])
    def api_printer_config():
        payload = request.get_json(silent=True) or {}
        ip = str(payload.get("ip", "")).strip()
        access_code = str(payload.get("access_code", payload.get("ACCESS_CODE", ""))).strip()
        serial_no = str(payload.get("serial_no", payload.get("SERIAL_NO", ""))).strip()
        if not runtime.is_valid_ipv4(ip):
            return jsonify({"success": False, "message": "Invalid printer IP."}), 400

        try:
            cfg = runtime.load_local_config()
            cfg["PRINTER_IP"] = ip
            if access_code:
                cfg["ACCESS_CODE"] = access_code
            if serial_no:
                cfg["SERIAL_NO"] = serial_no
            runtime.save_local_config(cfg)
            runtime._printer_reconnect_event.set()
            time.sleep(0.2)
            status = runtime.get_printer_status(force_refresh=False)
            msg = "Printer IP saved. Reconnecting..."
            if status.get("status") == "Connected":
                msg = "Printer IP saved and connected."
            missing_fields = [
                key for key in ("PRINTER_IP", "ACCESS_CODE", "SERIAL_NO")
                if not str(cfg.get(key, "")).strip()
            ]
            if missing_fields:
                if set(missing_fields) == {"ACCESS_CODE", "SERIAL_NO"}:
                    msg = "IP saved, but first-time printer pairing still needs ACCESS_CODE and SERIAL_NO."
                else:
                    msg = f"Printer config saved, but missing: {', '.join(missing_fields)}"
            return jsonify({
                "success": True,
                "message": msg,
                "printer": status,
                "missing_fields": missing_fields,
            })
        except Exception as e:
            return jsonify({"success": False, "message": f"Save failed: {e}"}), 500

    @app.route("/api/printer/refresh", methods=["POST"])
    def api_printer_refresh():
        status = runtime.get_printer_status(force_refresh=True)
        if status.get("status") == "Connected":
            return jsonify({"success": True, "message": "Printer connected.", "printer": status})
        return jsonify({
            "success": False,
            "message": f"Printer status: {status.get('status', 'Unknown')}",
            "printer": status,
        }), 200

    @app.route("/api/inspection/reset", methods=["POST"])
    def api_inspection_reset():
        runtime.start_inspection_session()
        with runtime.data_lock:
            part_id = int(runtime.part_session.get("part_id") or 0)
        return jsonify({
            "success": True,
            "part_id": part_id,
            "current_side": 1,
            "message": "Inspection session reset.",
        })

    @app.route("/api/inspection/cancel", methods=["POST"])
    def api_inspection_cancel():
        with runtime.data_lock:
            runtime.inspection_active = False
            runtime.part_session = runtime.reset_part_session()
            runtime.locked_overlay = None
            runtime.latest_ai_results = runtime.default_ai_results(1)
            runtime.overlay_block_until = 0.0
            runtime.reset_side_observation(1)
        runtime.set_side3_measurement_armed(False)
        runtime.set_side3_manual_preview_enabled(False)
        return jsonify({
            "success": True,
            "current_side": 1,
            "message": "System Ready cancelled.",
        })

    @app.route("/api/inspection/side3_measurement_arm", methods=["POST"])
    def api_side3_measurement_arm():
        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled"))
        runtime.set_side3_measurement_armed(enabled)
        return jsonify({
            "success": True,
            "enabled": enabled,
        })

    @app.route("/api/side3/preview", methods=["POST"])
    def api_side3_preview():
        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled"))
        runtime.set_side3_manual_preview_enabled(enabled)
        return jsonify({
            "success": True,
            "enabled": enabled,
        })

    @app.route("/api/side3/calibration/capture", methods=["POST"])
    def api_side3_calibration_capture():
        payload = request.get_json(silent=True) or {}
        frame = runtime.get_raw_frame_snapshot()
        if frame is None:
            return jsonify({"success": False, "message": "No frame available for SIDE 3 calibration."}), 503

        cfg = runtime.load_local_config()
        known_height_mm = payload.get("height_mm")
        if known_height_mm is None:
            known_height_mm = cfg.get("SIDE3_GAGEBOX_HEIGHT_MM")

        calibration_measurement = None
        try:
            calibration_measurement = runtime.measure_calibration_box_from_frame(
                frame,
                runtime.get_side3_measurement_settings()["scale_mm_per_pixel"],
                known_height_mm,
            )
        except Exception:
            calibration_measurement = None

        calibration_dir = os.path.join(runtime.BASE_DIR, "calibration")
        os.makedirs(calibration_dir, exist_ok=True)

        captured_at_dt = datetime.datetime.now()
        filename = f"side3_reference_{captured_at_dt.strftime('%Y%m%d_%H%M%S')}.jpg"
        local_path = os.path.join(calibration_dir, filename)

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not ok:
            return jsonify({"success": False, "message": "Failed to encode SIDE 3 calibration image."}), 500

        with open(local_path, "wb") as fh:
            fh.write(buf.tobytes())

        cfg["SIDE3_REFERENCE_IMAGE"] = local_path
        cfg["SIDE3_REFERENCE_CAPTURED_AT"] = captured_at_dt.isoformat()
        scale_candidates = []
        for payload_key, config_key in (
            ("width_mm", "SIDE3_GAGEBOX_WIDTH_MM"),
            ("length_mm", "SIDE3_GAGEBOX_LENGTH_MM"),
            ("height_mm", "SIDE3_GAGEBOX_HEIGHT_MM"),
        ):
            raw_value = payload.get(payload_key)
            try:
                parsed = float(raw_value) if raw_value is not None else None
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and parsed > 0:
                cfg[config_key] = parsed
                if calibration_measurement is not None:
                    if payload_key == "width_mm":
                        width_px = float(calibration_measurement.get("width_px") or 0.0)
                        if width_px > 0:
                            scale_candidates.append(parsed / width_px)
                    elif payload_key == "length_mm":
                        length_px = float(calibration_measurement.get("length_px") or 0.0)
                        if length_px > 0:
                            scale_candidates.append(parsed / length_px)
        applied_scale = None
        if scale_candidates:
            applied_scale = sum(scale_candidates) / len(scale_candidates)
            cfg["SIDE3_SCALE_MM_PER_PIXEL"] = applied_scale
        runtime.save_local_config(cfg)

        return jsonify({
            "success": True,
            "message": "SIDE 3 calibration reference captured.",
            "path": local_path,
            "filename": filename,
            "captured_at": captured_at_dt.isoformat(),
            "applied_scale_mm_per_pixel": applied_scale,
            "gage_box": {
                "width_mm": cfg.get("SIDE3_GAGEBOX_WIDTH_MM"),
                "length_mm": cfg.get("SIDE3_GAGEBOX_LENGTH_MM"),
                "height_mm": cfg.get("SIDE3_GAGEBOX_HEIGHT_MM"),
            },
        })

    @app.route("/api/inspection/side", methods=["POST"])
    def api_inspection_side():
        payload = request.get_json(silent=True) or {}
        side = int(payload.get("side") or 0)
        label = str(payload.get("label") or "").strip()
        active_sides = tuple(getattr(runtime, "ACTIVE_INSPECTION_SIDES", (1, 2)))

        with runtime.data_lock:
            active = runtime.inspection_active
            expected_side = runtime.part_session["current_side"]

        if not active:
            return jsonify({"success": False, "message": "Inspection session is not active."}), 400
        if side not in active_sides:
            return jsonify({"success": False, "message": "Invalid side."}), 400
        if side != expected_side:
            return jsonify({"success": False, "message": f"Expected side {expected_side}, got side {side}."}), 400
        if not label:
            return jsonify({"success": False, "message": "Missing label."}), 400
        if side == 3:
            frame = runtime.get_raw_frame_snapshot()
            if frame is None:
                return jsonify({"success": False, "message": "No SIDE3 frame available yet."}), 409
            try:
                measure_settings = runtime.get_side3_measurement_settings()
                measurement = runtime.measure_side3_from_frame(
                    frame,
                    measure_settings["scale_mm_per_pixel"],
                )
            except Exception:
                return jsonify({"success": False, "message": "No part detected on SIDE 3."}), 409
            if not runtime.has_valid_side3_detection(measurement):
                return jsonify({"success": False, "message": "SIDE 3 is still empty. Place the part before inspection."}), 409

        result = runtime.finalize_current_side(side, label)
        return jsonify({
            "success": True,
            "saved_label": result["saved_label"],
            "defect_label": result["defect_label"],
            "part_complete": result["part_complete"],
            "next_side": result["next_side"],
            "final_result": result["final_result"],
            "dimensions": result.get("dimensions"),
            "measurement_message": result.get("measurement_message"),
        })

    @app.route("/restart", methods=["POST"])
    def restart_server():
        runtime.clear_runtime_state()

        def do_restart():
            time.sleep(0.3)
            subprocess.Popen(
                ["/bin/bash", os.path.join(runtime.BASE_DIR, "run_app.sh")],
                start_new_session=True,
            )

        threading.Thread(target=do_restart, daemon=True).start()
        return jsonify({"success": True, "message": "Restarting server and clearing inspection history."})

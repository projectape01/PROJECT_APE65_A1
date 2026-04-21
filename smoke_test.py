import json

import app as app_module


def main():
    client = app_module.app.test_client()
    checks = []

    checks.append(("runtime subprocess imported", hasattr(app_module, "subprocess"), None, "ok"))

    resp = client.get("/")
    checks.append(("GET /", resp.status_code, resp.content_type, "ok"))

    resp = client.get("/get_status")
    body = resp.get_json(silent=True) or {}
    checks.append(("GET /get_status", resp.status_code, sorted(list(body.keys()))[:6], "ok"))

    resp = client.post("/api/capture", json={"folder": "smoke"})
    checks.append(("POST /api/capture", resp.status_code, resp.get_json(silent=True), "ok"))

    resp = client.post("/api/inspection/reset")
    checks.append(("POST /api/inspection/reset", resp.status_code, resp.get_json(silent=True), "ok"))

    resp = client.post("/api/inspection/side", json={"side": 1, "label": "GOOD"})
    checks.append(("POST /api/inspection/side", resp.status_code, resp.get_json(silent=True), "ok"))

    resp = client.post("/api/modbus/trigger", json={"addr": 7})
    checks.append(("POST /api/modbus/trigger", resp.status_code, resp.get_json(silent=True), "ok"))

    resp = client.post("/api/printer/refresh")
    checks.append(("POST /api/printer/refresh", resp.status_code, resp.get_json(silent=True), "ok"))

    resp = client.post("/toggle_system")
    checks.append(("POST /toggle_system off", resp.status_code, resp.get_json(silent=True), "ok"))

    resp = client.post("/toggle_system")
    checks.append(("POST /toggle_system on", resp.status_code, resp.get_json(silent=True), "ok"))

    for item in checks:
        print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()

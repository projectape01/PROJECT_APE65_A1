import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_http_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


http_session = build_http_session()


def post_json_with_retry(url, payload, headers, timeout=(3.0, 10.0)):
    return http_session.post(url, json=payload, headers=headers, timeout=timeout)


def get_json_with_retry(url, headers, timeout=(3.0, 10.0)):
    return http_session.get(url, headers=headers, timeout=timeout)


def parse_missing_schema_column(response_text):
    text = str(response_text or "")
    match = re.search(r"Could not find the '([^']+)' column", text)
    return match.group(1) if match else None


def post_json_pruning_unknown_columns(url, payload, headers, timeout=(3.0, 10.0), max_attempts=None):
    working_payload = dict(payload or {})
    removed_columns = []
    attempts_left = max_attempts or max(1, len(working_payload))
    last_response = None

    while attempts_left > 0 and working_payload:
        last_response = post_json_with_retry(url, working_payload, headers, timeout=timeout)
        if last_response.status_code in (200, 201):
            return last_response, removed_columns, working_payload

        if last_response.status_code != 400:
            return last_response, removed_columns, working_payload

        missing_column = parse_missing_schema_column(last_response.text)
        if not missing_column or missing_column not in working_payload:
            return last_response, removed_columns, working_payload

        removed_columns.append(missing_column)
        working_payload.pop(missing_column, None)
        attempts_left -= 1

    return last_response, removed_columns, working_payload

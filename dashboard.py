import time
import html
import base64
import os
import json
from collections import Counter
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

# --- Configuration ---
DEFAULT_SUPABASE_URL = "https://ptxfbxwufbrivfrcplku.supabase.co"
DEFAULT_SUPABASE_KEY = ""
SYSTEM_REFRESH_SECONDS = 120
PART_RECORDS_REFRESH_SECONDS = 120
DASHBOARD_AUTO_REFRESH_SECONDS = 120
SUPABASE_TIMEOUT_SECONDS = 4
SYSTEM_STATUS_STALE_SECONDS = 150
CHART_CONFIG = {"displayModeBar": False, "staticPlot": True, "responsive": True}
PART_RECORDS_FETCH_LIMIT = None
HISTORY_ROWS_RENDER_LIMIT = 18
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DIMENSION_TARGETS = {
    "top": (19.20, 19.80),
    "bottom": (24.20, 24.80),
    "length": (89.70, 90.30),
}
DIMENSION_CHART_FIELDS = {
    "top": {
        "label": "TOP",
        "keys": ["dimension of top", "dim_top", "top", "dimension_top", "top_mm", "top_value"],
    },
    "bottom": {
        "label": "BOTTOM",
        "keys": ["dimension of bottom", "dim_bottom", "bottom", "dimension_bottom", "bottom_mm", "bottom_value"],
    },
    "length": {
        "label": "LENGTH",
        "keys": ["dimension of length", "dim_length", "length", "dimension_length", "length_mm", "length_value"],
    },
}


def load_local_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_secret_or_env(name, default=""):
    local_cfg = load_local_config()
    try:
        if name in st.secrets:
            value = st.secrets[name]
            if value not in (None, ""):
                return str(value)
    except Exception:
        pass

    env_value = os.getenv(name)
    if env_value not in (None, ""):
        return str(env_value)
    cfg_value = local_cfg.get(name)
    if cfg_value not in (None, ""):
        return str(cfg_value)
    return str(default)


SUPABASE_URL = get_secret_or_env("SUPABASE_URL", DEFAULT_SUPABASE_URL).rstrip("/")
SUPABASE_KEY = get_secret_or_env("SUPABASE_KEY", DEFAULT_SUPABASE_KEY).strip()

st.set_page_config(
    page_title="Production Monitor",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LIGHT_THEME = {
    "bg": "#f3f1ec",
    "bg_accent": "#ebe7de",
    "surface": "rgba(255,255,255,0.9)",
    "surface_strong": "#ffffff",
    "surface_soft": "#f8f6f1",
    "border": "#ddd7cb",
    "border_strong": "#c8c0b3",
    "text_1": "#171512",
    "text_2": "#5a564f",
    "text_3": "#8d867b",
    "green": "#1d7a4f",
    "green_bg": "#edf7f2",
    "green_bd": "#b4dfc8",
    "red": "#ba4335",
    "red_bg": "#fcf0ee",
    "red_bd": "#efc0bb",
    "amber": "#af650f",
    "amber_bg": "#fbf3e8",
    "amber_bd": "#e4c391",
    "blue": "#2458a6",
    "blue_bg": "#edf3fc",
    "blue_bd": "#c9d9f5",
    "shadow": "0 18px 50px rgba(37, 29, 14, 0.06)",
}

DARK_THEME = {
    "bg": "#151a20",
    "bg_accent": "#1d242c",
    "surface": "rgba(26,32,40,0.92)",
    "surface_strong": "#202833",
    "surface_soft": "#28313c",
    "border": "#394452",
    "border_strong": "#4a5869",
    "text_1": "#eef3f7",
    "text_2": "#b2beca",
    "text_3": "#8b99a8",
    "green": "#70d69d",
    "green_bg": "#1e3a2d",
    "green_bd": "#356a50",
    "red": "#f08b81",
    "red_bg": "#442a2d",
    "red_bd": "#6a4248",
    "amber": "#f0be74",
    "amber_bg": "#463821",
    "amber_bd": "#6f5934",
    "blue": "#8eb8ff",
    "blue_bg": "#243652",
    "blue_bd": "#45638d",
    "shadow": "0 20px 54px rgba(0, 0, 0, 0.28)",
}


def current_theme_tokens(theme_mode):
    normalized = str(theme_mode).strip()
    return DARK_THEME if normalized in {"Dark", "☾"} else LIGHT_THEME


def is_dark_theme(theme_mode):
    return str(theme_mode).strip() in {"Dark", "☾"}


if "dashboard_theme_mode" not in st.session_state:
    st.session_state["dashboard_theme_mode"] = "☀"

theme_mode = st.session_state.get("dashboard_theme_mode", "☀")
theme = current_theme_tokens(theme_mode)


def logo_data_uri():
    logo_path = os.path.join(BASE_DIR, "static", "tme-logo.png")
    try:
        with open(logo_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


logo_uri = logo_data_uri()

st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

    :root {
        --bg: #f3f1ec;
        --bg-accent: #ebe7de;
        --surface: rgba(255,255,255,0.9);
        --surface-strong: #ffffff;
        --surface-soft: #f8f6f1;
        --border: #ddd7cb;
        --border-strong: #c8c0b3;
        --text-1: #171512;
        --text-2: #5a564f;
        --text-3: #8d867b;
        --green: #1d7a4f;
        --green-bg: #edf7f2;
        --green-bd: #b4dfc8;
        --red: #ba4335;
        --red-bg: #fcf0ee;
        --red-bd: #efc0bb;
        --amber: #af650f;
        --amber-bg: #fbf3e8;
        --amber-bd: #e4c391;
        --blue: #2458a6;
        --blue-bg: #edf3fc;
        --blue-bd: #c9d9f5;
        --shadow: 0 18px 50px rgba(37, 29, 14, 0.06);
        --radius: 14px;
        --stack-gap: clamp(6px, 0.9vh, 10px);
        --box-gap: clamp(6px, 0.9vh, 10px);
        --card-head-top: clamp(10px, 1.2vh, 14px);
        --card-head-bottom: 10px;
        --bottom-row-height: clamp(156px, 19vh, 188px);
        --chart-row-height: calc(var(--bottom-row-height) + 30px);
        --bottom-chart-height: clamp(104px, 13vh, 124px);
        --recent-table-height: 244px;
        --recent-card-height: 286px;
        --inspect-card-min-height: 250px;
        --bambu-card-min-height: 176px;
        --left-empty-card-min-height: 168px;
        --detail-min-height: clamp(152px, 18vh, 186px);
        --capture-min-height: clamp(140px, 16.5vh, 162px);
        --font: 'Space Grotesk', sans-serif;
        --mono: 'IBM Plex Mono', monospace;
    }

    html, body, [data-testid="stAppViewContainer"] {
        background: transparent !important;
        background-image: none !important;
        color: var(--text-1);
        font-family: var(--font);
        margin: 0 !important;
        padding: 0 !important;
        overflow-x: hidden !important;
        overflow-y: hidden !important;
        height: 100% !important;
    }
    [data-testid="stAppViewContainer"],
    [data-testid="stApp"],
    section[data-testid="stMain"] {
        background: transparent !important;
        background-image: none !important;
        box-shadow: none !important;
        border: 0 !important;
        margin: 0 !important;
        padding: 0 8px 0 8px !important;
        box-sizing: border-box !important;
        overflow-x: hidden !important;
        overflow-y: hidden !important;
    }
    [data-testid="stAppViewContainer"] {
        border: 1px solid var(--border-strong) !important;
        box-sizing: border-box !important;
        min-height: 100vh !important;
        height: 100vh !important;
    }
    [data-testid="stAppViewContainer"] > .main,
    [data-testid="stAppViewContainer"] > .main > div {
        width: 100% !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 0 !important;
        height: 100% !important;
    }
    section[data-testid="stMain"] > div {
        width: 100% !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 0 !important;
        height: 100% !important;
    }
    .main { background: transparent; }
    .mobile-topbar-spacer {
        display: none;
        width: 100%;
        height: 0;
    }
    .block-container {
        width: 100% !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 0 8px 0 8px !important;
        box-sizing: border-box !important;
        overflow: hidden !important;
    }
    div[data-testid="stMainBlockContainer"] {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        outline: 0 !important;
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        padding: 0 8px 8px 8px !important;
        margin: 0 !important;
        min-height: calc(100vh - 2px) !important;
        height: calc(100vh - 2px) !important;
        overflow: hidden !important;
    }
    div[data-testid="stMainBlockContainer"] > div:first-child,
    .block-container > div:first-child {
        margin-top: 0 !important;
        padding-top: 0 !important;
        min-height: 0 !important;
        height: auto !important;
    }
    div[data-testid="stMainBlockContainer"] > div:first-child > div:first-child {
        margin-top: 0 !important;
        padding-top: 0 !important;
        min-height: 0 !important;
        height: auto !important;
    }
    #MainMenu, footer, header { visibility: hidden; }
    header[data-testid="stHeader"] {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
    }
    div[data-testid="stToolbar"] {
        display: none !important;
        height: 0 !important;
    }
    div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    [data-testid="stVerticalBlock"] { gap: var(--stack-gap) !important; }
    [data-testid="stVerticalBlock"] > div {
        margin-bottom: 12px !important;
    }
    [data-testid="stVerticalBlock"] > div:last-child {
        margin-bottom: 0 !important;
    }
    div.stElementContainer {
        margin-bottom: 12px !important;
    }
    div.stElementContainer:last-child {
        margin-bottom: 0 !important;
    }
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        gap: var(--stack-gap) !important;
    }
    [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] {
        margin-bottom: 12px !important;
    }
    [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:last-child {
        margin-bottom: 0 !important;
    }
    .topbar,
    .card,
    .status-card {
        margin-bottom: var(--box-gap) !important;
    }
    .topbar:last-child,
    .card:last-child,
    .status-card:last-child {
        margin-bottom: 0 !important;
    }
    .card > .stat-grid,
    .card > .printer-task,
    .card > .meta-grid,
    .card > .printer-grid,
    .card > .progress-wrap,
    .card > .record-grid,
    .card > .chart-grid,
    .status-card > .status-head,
    .status-card > .status-list {
        margin-bottom: var(--box-gap) !important;
    }
    .card > :last-child,
    .status-card > :last-child {
        margin-bottom: 0 !important;
    }
    .stat-grid,
    .printer-grid,
    .meta-grid,
    .q-grid,
    .record-grid,
    .chart-grid,
    .status-list,
    .side-grid,
    .capture-grid,
    .inspection-layout {
        gap: var(--box-gap) !important;
        row-gap: var(--box-gap) !important;
        column-gap: var(--box-gap) !important;
    }
    [data-testid="stVerticalBlock"] > div:has(> .topbar),
    [data-testid="stVerticalBlock"] > div:has(> .card),
    [data-testid="stVerticalBlock"] > div:has(> .status-card),
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)),
    div[data-testid="stVerticalBlock"]:has(#recent-records-anchor):not(:has(div[data-testid="stVerticalBlock"] #recent-records-anchor)) {
        margin-bottom: 8px !important;
    }
    [data-testid="stVerticalBlock"] > div:has(> .topbar) {
        margin-bottom: 0 !important;
        height: 0 !important;
        min-height: 0 !important;
        padding: 0 !important;
        overflow: visible !important;
    }
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div:first-child:has(> .status-card),
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div:first-child:has(> .card) {
        margin-top: -10px !important;
        padding-top: 0 !important;
    }
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div:first-child:has(> .status-card) .status-card,
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div:first-child:has(> .card) .card {
        margin-top: 0 !important;
    }
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div:first-child:has(> .status-card) div.stElementContainer,
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > div:first-child:has(> .card) div.stElementContainer {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    div.stElementContainer:has(.topbar) {
        margin: 0 !important;
        padding: 0 !important;
        height: 0 !important;
        min-height: 0 !important;
        overflow: visible !important;
    }
    div.stElementContainer:has(.floating-topbar-shell) {
        margin: 0 !important;
        padding: 0 !important;
        height: 0 !important;
        min-height: 0 !important;
        overflow: visible !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) {
        margin-bottom: 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):has(#ng-chart-anchor) {
        gap: 8px !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):has(#ng-chart-anchor) > div:has(.q-grid) {
        margin-bottom: 12px !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):has(#ng-chart-anchor) > div:has(#inspection-card-anchor) {
        margin-bottom: 0 !important;
    }
    div.stElementContainer:has(#inspection-card-anchor),
    [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(#inspection-card-anchor) {
        margin-bottom: 0 !important;
    }

    .topbar {
        display: grid;
        grid-template-columns: 1fr;
        align-items: start;
        gap: 6px;
        width: calc(100vw - 92px);
        min-width: 0;
        max-width: calc(100vw - 92px);
        padding: 8px 14px 10px;
        margin-top: 0 !important;
        margin-bottom: 0;
        background: linear-gradient(135deg, var(--surface-strong), var(--surface));
        border: 1px solid rgba(200, 192, 179, 0.75);
        border-radius: 18px;
        box-shadow: var(--shadow);
        backdrop-filter: blur(8px);
        position: fixed;
        top: 8px;
        left: 18px;
        right: auto;
        z-index: 9998;
    }
    .topbar-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }
    .topbar-kicker {
        font-size: 0.68rem;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--text-3);
    }
    .topbar-name {
        font-size: 1.02rem;
        font-weight: 700;
        color: var(--text-1);
        white-space: normal;
        line-height: 1.15;
        flex: 1 1 auto;
        min-width: 0;
    }
    .topbar-name-accent {
        color: #9a6408;
    }
    .topbar-info {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        flex-wrap: wrap;
    }
    .theme-toolbar button {
        min-width: 44px !important;
        height: 34px !important;
        padding: 0 12px !important;
        border-radius: 999px !important;
        border: 1px solid var(--blue-bd) !important;
        background: linear-gradient(180deg, var(--blue-bg), color-mix(in srgb, var(--blue-bd) 78%, var(--surface-strong))) !important;
        color: var(--blue) !important;
        box-shadow: inset 0 1px 0 color-mix(in srgb, var(--surface-strong) 35%, transparent), 0 3px 10px color-mix(in srgb, var(--blue-bd) 24%, transparent) !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
        white-space: nowrap !important;
    }
    div.stElementContainer:has(.theme-inline-anchor) {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div.stElementContainer:has(.theme-inline-anchor) + div[data-testid="stElementContainer"] {
        margin: 0 !important;
        padding: 0 !important;
    }
    div.stElementContainer:has(.theme-inline-anchor) + div[data-testid="stElementContainer"] [data-testid="stButton"] {
        width: 100% !important;
        margin: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    div.stElementContainer:has(.theme-inline-anchor) + div[data-testid="stElementContainer"] button {
        min-width: 44px !important;
        height: 36px !important;
        width: 100% !important;
        padding: 0 12px !important;
        border-radius: 999px !important;
        border: 1px solid var(--blue-bd) !important;
        background: linear-gradient(180deg, var(--blue-bg), color-mix(in srgb, var(--blue-bd) 78%, var(--surface-strong))) !important;
        color: var(--blue) !important;
        box-shadow: inset 0 1px 0 color-mix(in srgb, var(--surface-strong) 35%, transparent), 0 3px 10px color-mix(in srgb, var(--blue-bd) 24%, transparent) !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
        white-space: nowrap !important;
    }
    div.stElementContainer:has(.theme-floating-anchor) {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div.stElementContainer:has(.theme-floating-anchor) + div[data-testid="stElementContainer"] {
        position: fixed !important;
        top: 8px !important;
        right: 18px !important;
        z-index: 9999 !important;
        width: 50px !important;
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    div.stElementContainer:has(.theme-floating-anchor) + div[data-testid="stElementContainer"] [data-testid="stButton"] {
        width: 50px !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    div.stElementContainer:has(.theme-floating-anchor) + div[data-testid="stElementContainer"] button[kind="secondary"],
    div.stElementContainer:has(.theme-floating-anchor) + div[data-testid="stElementContainer"] button {
        min-width: 50px !important;
        width: 50px !important;
        height: 44px !important;
        padding: 0 !important;
        border-radius: 18px !important;
        background: linear-gradient(135deg, var(--surface-strong), var(--surface)) !important;
        color: var(--text-1) !important;
        border: 1px solid rgba(200, 192, 179, 0.75) !important;
        box-shadow: var(--shadow) !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
    }
    .topbar-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        font-family: var(--mono);
        font-size: 0.72rem;
        color: var(--text-2);
        white-space: nowrap;
    }
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        white-space: nowrap;
        padding: 8px 12px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        border: 1px solid var(--border);
        background: color-mix(in srgb, var(--surface-strong) 78%, transparent);
    }
    .status-pill.good { color: var(--green); background: var(--green-bg); border-color: var(--green-bd); }
    .status-pill.warn { color: #c96f13; background: #fff1df; border-color: #efbb77; }
    .status-pill.bad { color: var(--red); background: var(--red-bg); border-color: var(--red-bd); }

    .card {
        background: linear-gradient(180deg, var(--surface-strong), var(--surface));
        border: 1px solid rgba(221, 215, 203, 0.9);
        border-radius: var(--radius);
        padding: 10px 14px 12px;
        box-shadow: var(--shadow);
        backdrop-filter: blur(6px);
    }
    .card-bambu {
        min-height: var(--bambu-card-min-height);
        padding-bottom: 10px !important;
    }
    .card-empty {
        min-height: var(--left-empty-card-min-height);
        height: var(--left-empty-card-min-height);
        overflow: hidden;
    }
    .project-info {
        display: grid;
        gap: 6px;
    }
    .info-panel {
        padding: 7px 9px;
        border-radius: 12px;
        border: 1px solid var(--border-strong);
        background: linear-gradient(180deg, color-mix(in srgb, var(--bg-accent) 52%, var(--surface-strong)), color-mix(in srgb, var(--surface-soft) 82%, var(--bg-accent)));
    }
    .info-panel.compact {
        padding: 7px 9px;
    }
    .info-kicker {
        font-size: 0.58rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #5f543f;
        margin-bottom: 3px;
    }
    .info-body {
        font-size: 0.72rem;
        line-height: 1.35;
        color: var(--text-1);
    }
    .info-grid {
        display: grid;
        gap: 6px;
    }
    .info-columns {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
        align-items: stretch;
    }
    .info-columns > .info-panel {
        height: 100%;
    }
    .info-row {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 6px;
        align-items: center;
        padding: 3px 0;
        border-bottom: 1px solid rgba(221,215,203,0.55);
    }
    .info-row:last-child {
        border-bottom: none;
        padding-bottom: 0;
    }
    .info-label {
        font-size: 0.58rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #5f543f;
    }
    .info-value {
        font-size: 0.68rem;
        line-height: 1.25;
        color: #201c16;
        text-align: right;
    }
    .info-value.creators {
        display: grid;
        gap: 1px;
        font-size: 0.66rem;
        text-align: left;
    }
    .info-split {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
    }
    .info-value strong {
        color: var(--text-1);
        font-family: var(--mono);
    }
    .project-logo-wrap {
        display: flex;
        justify-content: center;
        align-items: center;
        margin-top: -8px;
        padding-top: 0;
    }
    .project-logo {
        max-height: 56px;
        width: auto;
        object-fit: contain;
        filter: drop-shadow(0 4px 8px rgba(0,0,0,0.12));
    }
    .card:has(.stat-grid),
    .card:has(.printer-task) {
        padding-bottom: 14px;
    }
    .card-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
    }
    .card-title-left {
        display: flex;
        align-items: center;
        gap: 9px;
    }
    .card-label {
        font-size: 0.9rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--text-1);
    }
    .card-note {
        font-size: 0.8rem;
        color: var(--text-2);
        font-family: var(--mono);
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) {
        background: linear-gradient(180deg, var(--surface-strong), var(--surface)) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        padding: 10px 14px 30px !important;
        min-height: var(--inspect-card-min-height) !important;
        box-shadow: var(--shadow) !important;
        backdrop-filter: blur(6px) !important;
        --inspect-ctl-h: 26px;
        --inspect-ctl-font: 0.72rem;
    }
    div[data-testid="stVerticalBlock"]:has(#recent-records-anchor):not(:has(div[data-testid="stVerticalBlock"] #recent-records-anchor)) {
        background: linear-gradient(180deg, var(--surface-strong), var(--surface)) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        padding: 6px 12px 10px !important;
        margin-top: 0 !important;
        margin-left: auto !important;
        margin-right: 0 !important;
        width: min(100%, 420px) !important;
        max-width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
        height: var(--recent-card-height) !important;
        justify-self: end !important;
        align-self: start !important;
        box-shadow: var(--shadow) !important;
        backdrop-filter: blur(6px) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#ng-chart-anchor):not(:has(div[data-testid="stVerticalBlock"] #ng-chart-anchor)),
    div[data-testid="stVerticalBlock"]:has(#trend-chart-anchor):not(:has(div[data-testid="stVerticalBlock"] #trend-chart-anchor)) {
        background: linear-gradient(180deg, var(--surface-strong), var(--surface)) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        padding: 10px 12px 8px !important;
        margin-top: 0 !important;
        height: var(--chart-row-height) !important;
        box-shadow: var(--shadow) !important;
        backdrop-filter: blur(6px) !important;
        margin-bottom: 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(#trend-chart-anchor):not(:has(div[data-testid="stVerticalBlock"] #trend-chart-anchor)) {
        padding: 0 12px 8px !important;
        position: relative !important;
    }
    div[data-testid="stHorizontalBlock"]:has(#ng-chart-anchor):has(#trend-chart-anchor) {
        gap: 12px !important;
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
        align-items: stretch !important;
    }
    div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stHorizontalBlock"]:has(#ng-chart-anchor):has(#trend-chart-anchor)) {
        margin-top: -12px !important;
        margin-bottom: 0 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(#ng-chart-anchor):has(#trend-chart-anchor) > div[data-testid="stColumn"] {
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-controls-anchor) > div[data-testid="stHorizontalBlock"] {
        gap: 0.22rem !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-controls-anchor) > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        min-width: 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-testid="stTextInput"] input {
        width: 100% !important;
        min-height: var(--inspect-ctl-h) !important;
        height: var(--inspect-ctl-h) !important;
        line-height: calc(var(--inspect-ctl-h) - 2px) !important;
        font-size: var(--inspect-ctl-font) !important;
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
        border: 0 !important;
        -webkit-text-fill-color: var(--text-1) !important;
        caret-color: var(--text-1) !important;
        padding: 0 8px !important;
        margin: 0 !important;
        box-sizing: border-box !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-testid="stTextInput"] > div,
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-testid="stTextInput"] > div > div,
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="input"],
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="input"] > div {
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
        border: 1px solid var(--border) !important;
        border-radius: 8px !important;
        box-shadow: none !important;
        min-height: var(--inspect-ctl-h) !important;
        height: var(--inspect-ctl-h) !important;
        box-sizing: border-box !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        display: flex !important;
        align-items: center !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-testid="stTextInput"] {
        width: 100% !important;
        min-height: var(--inspect-ctl-h) !important;
        height: var(--inspect-ctl-h) !important;
        margin: 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="input"] {
        min-height: var(--inspect-ctl-h) !important;
        height: var(--inspect-ctl-h) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-testid="stTextInput"] input::placeholder {
        color: var(--text-3) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] > div {
        min-height: var(--inspect-ctl-h) !important;
        height: var(--inspect-ctl-h) !important;
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
        border: 1px solid var(--border) !important;
        box-shadow: none !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        display: flex !important;
        align-items: center !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"],
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] > div > div,
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] input {
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
        -webkit-text-fill-color: var(--text-1) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] span {
        font-size: var(--inspect-ctl-font) !important;
        color: var(--text-1) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] input,
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] div {
        font-size: var(--inspect-ctl-font) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] * {
        color: var(--text-1) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] svg {
        fill: var(--text-2) !important;
    }
    /* Result filter (3rd control column): highlight PASS/FAIL */
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor))
    > div[data-testid="stHorizontalBlock"]
    > div[data-testid="stColumn"]:nth-child(3)
    [data-baseweb="select"]:has(input[value="PASS"]) > div {
        background: var(--green-bg) !important;
        border-color: var(--green-bd) !important;
        box-shadow: 0 0 0 1px rgba(29,122,79,0.18) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor))
    > div[data-testid="stHorizontalBlock"]
    > div[data-testid="stColumn"]:nth-child(3)
    [data-baseweb="select"]:has(input[value="PASS"]) span,
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor))
    > div[data-testid="stHorizontalBlock"]
    > div[data-testid="stColumn"]:nth-child(3)
    [data-baseweb="select"]:has(input[value="PASS"]) input {
        color: var(--green) !important;
        -webkit-text-fill-color: var(--green) !important;
        font-weight: 700 !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor))
    > div[data-testid="stHorizontalBlock"]
    > div[data-testid="stColumn"]:nth-child(3)
    [data-baseweb="select"]:has(input[value="FAIL"]) > div {
        background: var(--red-bg) !important;
        border-color: var(--red-bd) !important;
        box-shadow: 0 0 0 1px rgba(186,67,53,0.18) !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor))
    > div[data-testid="stHorizontalBlock"]
    > div[data-testid="stColumn"]:nth-child(3)
    [data-baseweb="select"]:has(input[value="FAIL"]) span,
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor))
    > div[data-testid="stHorizontalBlock"]
    > div[data-testid="stColumn"]:nth-child(3)
    [data-baseweb="select"]:has(input[value="FAIL"]) input {
        color: var(--red) !important;
        -webkit-text-fill-color: var(--red) !important;
        font-weight: 700 !important;
    }
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-testid="stTextInput"] input:focus,
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) [data-baseweb="select"] > div:focus-within {
        background: var(--surface-strong) !important;
        border-color: var(--border-strong) !important;
        box-shadow: 0 0 0 1px rgba(200, 192, 179, 0.35) !important;
    }
    /* Dropdown menu portal for select (Live/Search list) */
    div[data-baseweb="popover"] div[role="listbox"],
    div[data-baseweb="popover"] div[role="option"],
    div[data-baseweb="menu"],
    div[data-baseweb="menu"] * {
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
    }
    div[data-baseweb="popover"] ul,
    div[data-baseweb="popover"] li,
    div[data-baseweb="popover"] li > div,
    div[data-baseweb="popover"] [role="option"],
    div[data-baseweb="popover"] [aria-selected] {
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
        font-size: var(--inspect-ctl-font) !important;
    }
    div[data-baseweb="popover"] li:hover,
    div[data-baseweb="popover"] [role="option"]:hover,
    div[data-baseweb="popover"] [aria-selected="true"] {
        background: var(--surface-soft) !important;
        color: var(--text-1) !important;
    }

    .dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        display: inline-block;
        flex-shrink: 0;
    }
    .dot-on { background: var(--green); box-shadow: 0 0 0 4px rgba(29,122,79,0.12); }
    .dot-off { background: var(--red); box-shadow: 0 0 0 4px rgba(186,67,53,0.12); }
    .dot-warn { background: var(--amber); box-shadow: 0 0 0 4px rgba(175,101,15,0.12); }

    .stat-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin-bottom: 12px;
    }
    .stat-box {
        padding: 12px;
        border-radius: 12px;
        border: 1px solid var(--border);
        background: var(--surface-soft);
    }
    .stat-lbl {
        font-size: 0.64rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--text-3);
        margin-bottom: 6px;
    }
    .stat-val {
        font-size: 1.2rem;
        font-weight: 700;
        line-height: 1.1;
        color: var(--text-1);
        font-family: var(--mono);
    }
    .stat-sub {
        margin-top: 4px;
        font-size: 0.72rem;
        color: var(--text-2);
    }
    .bar-track {
        height: 5px;
        background: color-mix(in srgb, var(--border-strong) 78%, var(--surface-soft));
        border-radius: 999px;
        overflow: hidden;
        margin-top: 9px;
    }
    .bar-fill {
        height: 100%;
        border-radius: 999px;
    }
    .tone-good { background: linear-gradient(90deg, #4ebd82, #1d7a4f); }
    .tone-warn { background: linear-gradient(90deg, #e5a343, #af650f); }
    .tone-bad { background: linear-gradient(90deg, #df715d, #ba4335); }
    .tone-blue { background: linear-gradient(90deg, #6c9ae0, #2458a6); }

    .printer-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
        margin-bottom: 8px;
    }
    .temp-box {
        border-radius: 12px;
        padding: 9px 10px;
        background: var(--amber-bg);
        border: 1px solid var(--amber-bd);
    }
    .temp-box.cool {
        background: var(--blue-bg);
        border-color: var(--blue-bd);
    }
    .temp-num {
        font-size: 1.12rem;
        font-weight: 700;
        font-family: var(--mono);
        color: var(--text-1);
    }
    .temp-num.active { color: var(--red); }
    .temp-lbl {
        margin-top: 3px;
        font-size: 0.62rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--text-3);
    }
    .mini-progress {
        margin-top: 6px;
        height: 4px;
        border-radius: 999px;
        overflow: hidden;
        background: rgba(0,0,0,0.08);
    }
    .mini-fill {
        height: 100%;
        border-radius: 999px;
    }

    .meta-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
        margin-top: 6px;
    }
    .meta-box {
        padding: 9px 10px;
        border-radius: 12px;
        background: var(--surface-soft);
        border: 1px solid var(--border);
    }
    .meta-label {
        font-size: 0.64rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--text-3);
        margin-bottom: 4px;
    }
    .meta-value {
        font-size: 0.9rem;
        color: var(--text-1);
        font-weight: 600;
    }
    .printer-task {
        padding: 8px 10px;
        border-radius: 12px;
        background: var(--surface-soft);
        border: 1px solid var(--border);
        margin-bottom: 8px;
    }
    .printer-task-name {
        font-size: 0.96rem;
        font-weight: 700;
        color: var(--text-1);
        margin-top: 3px;
        line-height: 1.15;
        word-break: break-word;
    }
    .progress-wrap {
        margin-top: 6px;
        background: transparent;
        box-shadow: none;
        border: 0;
    }
    .progress-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 4px;
    }
    .progress-label {
        font-size: 0.66rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--text-3);
    }
    .progress-value {
        font-size: 0.82rem;
        font-family: var(--mono);
        color: var(--text-1);
        font-weight: 600;
    }
    .progress-track {
        width: 100%;
        height: 10px;
        border-radius: 999px;
        overflow: hidden;
        background: transparent;
        border: 1px solid color-mix(in srgb, var(--border) 55%, transparent);
    }
    .progress-fill {
        height: 100%;
        border-radius: 999px;
        background: linear-gradient(90deg, #8fb1e4, #2458a6);
    }
    .section-gap {
        margin-top: 8px;
    }

    .conn-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 11px 12px;
        background: var(--surface-soft);
        border: 1px solid var(--border);
        border-radius: 12px;
        margin-bottom: 12px;
    }
    .conn-item:last-child { margin-bottom: 0; }
    .conn-name {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.8rem;
        color: var(--text-2);
        font-weight: 600;
    }
    .conn-val {
        font-family: var(--mono);
        font-size: 0.76rem;
        font-weight: 600;
        color: var(--text-1);
    }
    .status-card {
        padding: 10px 12px 11px;
        border-radius: 12px;
        border: 1px solid var(--border);
        background: linear-gradient(180deg, var(--surface-strong), var(--surface));
        box-shadow: var(--shadow);
    }
    div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"]:first-child .status-card {
        min-height: 126px;
    }
    div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"]:first-child .card:not(.card-bambu) {
        min-height: 158px;
    }
    div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"]:first-child .card-bambu {
        min-height: 228px;
    }
    div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"]:first-child > div[data-testid="stVerticalBlock"] > div:last-child {
        margin-top: auto !important;
        margin-bottom: 8px !important;
    }
    .status-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 12px;
    }
    .status-title {
        font-size: 0.9rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--text-1);
    }
    .status-list {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px 12px;
    }
    .status-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 4px 0;
    }
    .status-row-name {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        color: var(--text-1);
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-row-note {
        font-size: 0.72rem;
        font-family: var(--mono);
        color: var(--text-2);
        white-space: nowrap;
    }
    .status-orb {
        position: relative;
        width: 10px;
        height: 10px;
        border-radius: 999px;
        flex-shrink: 0;
        border: 1px solid color-mix(in srgb, var(--surface-strong) 72%, transparent);
        background: color-mix(in srgb, var(--border-strong) 80%, var(--surface-soft));
        box-shadow:
            inset 0 1px 2px color-mix(in srgb, var(--surface-strong) 50%, transparent),
            0 0 0 2px rgba(0,0,0,0.04);
    }
    .status-orb::before {
        content: "";
        position: absolute;
        inset: -2px;
        border-radius: 999px;
        border: 1px solid rgba(0,0,0,0.06);
        background: transparent;
    }
    .status-orb.online {
        background:
            linear-gradient(180deg, #3ad88b 0%, #24a866 100%);
        box-shadow:
            inset 0 1px 1px color-mix(in srgb, var(--surface-strong) 35%, transparent),
            0 0 0 3px rgba(36,168,102,0.12);
    }
    .status-orb.warn {
        background:
            linear-gradient(180deg, #f0b35a 0%, #c17b24 100%);
        box-shadow:
            inset 0 1px 1px color-mix(in srgb, var(--surface-strong) 35%, transparent),
            0 0 0 3px rgba(193,123,36,0.12);
    }
    .status-orb.offline {
        background:
            linear-gradient(180deg, #ea6f61 0%, #c9483b 100%);
        box-shadow:
            inset 0 1px 1px color-mix(in srgb, var(--surface-strong) 35%, transparent),
            0 0 0 3px rgba(201,72,59,0.12);
    }

    .inspection-layout {
        display: grid;
        grid-template-columns: minmax(0, 1.35fr) minmax(0, 0.9fr);
        grid-template-areas:
            "capture detail"
            "sides detail"
            "result detail";
        column-gap: 10px;
        row-gap: 10px;
        align-items: stretch;
    }
    .capture-grid {
        grid-area: capture;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        grid-template-rows: 1fr;
        gap: 14px;
        align-items: stretch;
        align-content: center;
        min-width: 0;
        margin-top: 0;
        height: 100%;
    }
    .capture-cell {
        display: flex;
        min-width: 0;
        height: 100%;
    }
    .img-box {
        width: 100%;
        height: 100%;
        border-radius: 10px;
        border: 1px dashed var(--border-strong);
        background:
            linear-gradient(145deg, color-mix(in srgb, var(--surface-strong) 90%, transparent), color-mix(in srgb, var(--surface-soft) 96%, var(--bg-accent)));
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 3px;
        color: var(--text-3);
        text-align: center;
        padding: 6px;
        min-height: var(--capture-min-height);
    }
    .img-box.has-image {
        position: relative;
        overflow: hidden;
        border-style: solid;
        padding: 0;
        justify-content: flex-end;
        color: #fff;
    }
    .img-box.has-image::after {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(180deg, rgba(8, 12, 18, 0.08), rgba(8, 12, 18, 0.18));
        pointer-events: none;
    }
    .img-box.has-image img {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }
    .img-hitbox {
        position: absolute;
        inset: 0;
        z-index: 1;
        display: block;
        text-decoration: none;
    }
    .img-actions {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 2;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .img-action-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        min-height: 28px;
        padding: 0 10px;
        border-radius: 999px;
        background: rgba(10, 16, 24, 0.78);
        border: 1px solid rgba(255, 255, 255, 0.18);
        color: #fff;
        text-decoration: none;
        font-size: 0.58rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        backdrop-filter: blur(6px);
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
        transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease;
    }
    .img-action-btn:hover {
        transform: translateY(-1px);
        background: rgba(16, 26, 38, 0.9);
        border-color: rgba(255, 255, 255, 0.32);
    }
    .capture-gallery-modal {
        position: fixed;
        inset: 0;
        z-index: 10050;
        display: none;
        align-items: center;
        justify-content: center;
        width: 100vw;
        height: 100vh;
        padding: 0;
        background: rgba(0, 0, 0, 0.96);
        backdrop-filter: blur(6px);
    }
    .capture-gallery-modal:target {
        display: flex;
    }
    .capture-gallery-backdrop {
        position: absolute;
        inset: 0;
        display: block;
    }
    .capture-gallery-panel {
        position: relative;
        z-index: 1;
        width: min(96vw, 1520px);
        max-height: 96vh;
        display: flex;
        flex-direction: column;
        gap: 14px;
        padding: 18px 18px 18px;
        border-radius: 22px;
        background: rgba(8, 12, 18, 0.985);
        border: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 0 28px 100px rgba(0, 0, 0, 0.56);
    }
    .capture-gallery-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        color: #fff;
    }
    .capture-gallery-title {
        font-size: 0.96rem;
        font-weight: 800;
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }
    .capture-gallery-stage {
        color: rgba(255, 255, 255, 0.68);
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }
    .capture-gallery-x {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 38px;
        height: 38px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.12);
        color: #fff;
        text-decoration: none;
        font-size: 1.08rem;
        font-weight: 700;
    }
    .capture-gallery-body {
        position: relative;
        min-height: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        border-radius: 18px;
        background: rgba(0, 0, 0, 0.42);
    }
    .capture-gallery-body img {
        display: block;
        width: auto;
        height: auto;
        max-width: 100%;
        max-height: calc(96vh - 120px);
        object-fit: contain;
        border-radius: 16px;
    }
    .capture-gallery-x:hover {
        background: rgba(255, 255, 255, 0.12);
    }
    .img-caption {
        position: relative;
        z-index: 2;
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 3px;
        padding: 10px 12px;
        background: linear-gradient(180deg, rgba(9, 14, 20, 0.05), rgba(9, 14, 20, 0.88));
        text-align: left;
    }
    .img-box b {
        color: var(--text-2);
        font-size: 0.72rem;
        font-weight: 800;
    }
    .img-box span {
        font-size: 0.56rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-weight: 700;
    }
    .img-box.has-image b,
    .img-box.has-image span {
        color: #fff;
        text-shadow: 0 1px 8px rgba(0, 0, 0, 0.55);
    }

    .insp-grid {
        display: grid;
        grid-template-rows: auto auto;
        gap: 8px;
        min-width: 0;
    }
    .side-grid {
        grid-area: sides;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        min-width: 0;
    }
    .side-item, .overall-box, .dim-block {
        border-radius: 12px;
        border: 1px solid var(--border);
        background: var(--surface-soft);
    }
    .side-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 3px 7px !important;
        min-height: 28px !important;
        height: 28px !important;
        box-sizing: border-box;
    }
    .side-item.good {
        background: linear-gradient(145deg, #f3fbf6, #dff2e8);
        border-color: var(--green-bd);
    }
    .side-item.ng {
        background: linear-gradient(145deg, #fdf5f4, #f8ddda);
        border-color: var(--red-bd);
    }
    .side-name {
        font-size: 0.74rem;
        font-weight: 800;
        color: var(--text-2);
        letter-spacing: 0.04em;
        line-height: 1;
    }
    .side-badge {
        padding: 1px 8px !important;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 800;
        font-family: var(--mono);
        line-height: 1.1;
    }
    .badge-good { color: var(--green); background: color-mix(in srgb, var(--surface-strong) 86%, transparent); border: 1px solid var(--green-bd); }
    .badge-ng { color: var(--red); background: color-mix(in srgb, var(--surface-strong) 86%, transparent); border: 1px solid var(--red-bd); }
    .badge-neutral { color: var(--text-2); background: color-mix(in srgb, var(--surface-strong) 70%, transparent); }
    .side-item.good .side-name { color: var(--green); }
    .side-item.ng .side-name { color: var(--red); }
    .overall-box {
        padding: 4px 8px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        min-height: 42px;
        height: 42px;
        gap: 2px;
    }
    .overall-head {
        font-size: 0.58rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-weight: 800;
        color: var(--text-2);
        text-align: center;
        line-height: 1;
    }
    .overall-value {
        font-size: 0.82rem;
        font-family: var(--mono);
        font-weight: 800;
        letter-spacing: 0.04em;
        text-align: center;
        line-height: 1;
    }
    .overall-pass {
        color: var(--green);
        background: linear-gradient(145deg, #f3fbf6, #dff2e8);
        border-color: var(--green-bd);
    }
    .overall-fail {
        color: var(--red);
        background: linear-gradient(145deg, #fdf5f4, #f8ddda);
        border-color: var(--red-bd);
    }
    .overall-neutral { color: var(--text-2); }
    .dim-block {
        grid-area: detail;
        padding: 10px;
        min-height: var(--detail-min-height);
        display: flex;
        align-items: stretch;
        justify-content: center;
        min-width: 0;
    }
    .overall-box {
        grid-area: result;
    }
    .dim-row {
        display: flex;
        justify-content: space-between;
        padding: 3px 0;
        border-bottom: 1px solid var(--border);
        font-size: 0.68rem;
        color: var(--text-2);
    }
    .dim-row:last-child { border-bottom: none; }
    .dim-val {
        font-family: var(--mono);
        color: var(--text-1);
    }
    .record-panel {
        width: 100%;
        max-width: none;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 8px;
        background: transparent;
        box-shadow: none;
        border: 0;
    }
    .record-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 8px;
    }
    .record-part {
        font-size: 1.08rem;
        font-weight: 800;
        line-height: 1.15;
        color: var(--text-1);
        font-family: var(--mono);
        text-align: left;
        letter-spacing: 0.04em;
    }
    .record-ts {
        font-size: 0.68rem;
        color: var(--text-1);
        font-family: var(--mono);
        font-weight: 800;
        text-align: right;
        white-space: nowrap;
    }
    .record-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
    }
    .record-col {
        border: 1px solid var(--border);
        border-radius: 10px;
        background: transparent;
        padding: 8px;
        min-height: 152px;
        min-width: 0;
    }
    .record-col-title {
        font-size: 0.68rem;
        letter-spacing: 0.11em;
        text-transform: uppercase;
        color: var(--text-3);
        margin-bottom: 6px;
        font-weight: 800;
        text-align: center;
    }
    .record-line {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: center;
        gap: 6px;
        font-size: 0.72rem;
        padding: 4px 0;
        border-bottom: 1px solid rgba(221,215,203,0.72);
        color: var(--text-2);
    }
    .record-line span:first-child {
        min-width: 0;
        overflow-wrap: anywhere;
        word-break: break-word;
        white-space: normal;
    }
    .record-line .record-val {
        min-width: 0;
        overflow-wrap: anywhere;
        word-break: break-word;
        text-align: right;
    }
    .record-line:last-child {
        border-bottom: none;
    }
    .record-val {
        font-family: var(--mono);
        color: #171512;
        font-size: 0.74rem;
        font-weight: 700;
    }
    .record-val.dim-alert {
        color: var(--red) !important;
    }
    .record-val.defect {
        color: var(--red);
        font-weight: 700;
    }
    .dimension-target-note {
        margin-top: 4px;
        font-size: 0.58rem;
        line-height: 1.4;
        color: var(--text-2);
        text-align: left;
        font-family: var(--mono);
    }
    .dimension-target-note div + div {
        margin-top: 2px;
    }

    .q-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
    }
    .q-box {
        padding: 12px;
        border-radius: 12px;
        background: linear-gradient(180deg, color-mix(in srgb, var(--surface-soft) 82%, var(--surface-strong)), var(--surface-strong));
        border: 1px solid var(--border);
        text-align: center;
        box-shadow: inset 0 1px 0 color-mix(in srgb, var(--surface-strong) 50%, transparent);
    }
    .q-box.total {
        background: linear-gradient(180deg, color-mix(in srgb, var(--bg-accent) 72%, var(--surface-strong)), color-mix(in srgb, var(--surface-soft) 88%, var(--bg-accent)));
        border-color: color-mix(in srgb, var(--border-strong) 78%, var(--bg-accent));
    }
    .q-box.pass {
        background: linear-gradient(180deg, color-mix(in srgb, var(--green-bg) 75%, var(--surface-strong)), var(--green-bg));
        border-color: var(--green-bd);
    }
    .q-box.fail {
        background: linear-gradient(180deg, color-mix(in srgb, var(--red-bg) 75%, var(--surface-strong)), var(--red-bg));
        border-color: var(--red-bd);
    }
    .q-box.yield {
        background: linear-gradient(180deg, color-mix(in srgb, var(--blue-bg) 75%, var(--surface-strong)), var(--blue-bg));
        border-color: var(--blue-bd);
    }
    .q-num {
        font-size: 1.8rem;
        line-height: 1;
        font-weight: 700;
        font-family: var(--mono);
        color: var(--text-1);
    }
    .q-num.green { color: var(--green); }
    .q-num.red { color: var(--red); }
    .q-num.blue { color: var(--blue); }
    .q-sub {
        margin-top: 6px;
        font-size: 0.56rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--text-3);
    }

    .chart-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
    }
    .chart-shell {
        padding: 0;
        border-radius: 0;
        border: 0;
        background: transparent;
    }
    .chart-shell.tight {
        padding-bottom: 12px;
    }
    .chart-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 12px;
    }
    .chart-title {
        font-size: 0.64rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--text-3);
    }
    .chart-sub {
        font-size: 0.72rem;
        font-family: var(--mono);
        color: var(--text-2);
    }
    .chart-head.chart-head-main {
        justify-content: flex-start;
        margin-bottom: 4px;
    }
    .chart-title.chart-title-main {
        font-size: 0.9rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        color: var(--text-1);
    }
    div.stElementContainer:has(.dimension-select-anchor) {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div.stElementContainer:has(.dimension-select-anchor) + div[data-testid="stElementContainer"] {
        width: 128px !important;
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        position: absolute !important;
        top: 10px !important;
        right: 12px !important;
        z-index: 5 !important;
    }
    div.stElementContainer:has(.dimension-select-anchor) + div[data-testid="stElementContainer"] [data-testid="stSelectbox"] {
        max-width: 128px !important;
        margin-left: auto !important;
        width: 100% !important;
    }
    div.stElementContainer:has(.dimension-select-anchor) + div[data-testid="stElementContainer"] [data-baseweb="select"] > div {
        min-height: 32px !important;
        height: 32px !important;
        border-radius: 10px !important;
        background: var(--surface-strong) !important;
        border: 1px solid var(--border) !important;
        box-shadow: none !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    div.stElementContainer:has(.dimension-select-anchor) + div[data-testid="stElementContainer"] [data-baseweb="select"] span,
    div.stElementContainer:has(.dimension-select-anchor) + div[data-testid="stElementContainer"] [data-baseweb="select"] input,
    div.stElementContainer:has(.dimension-select-anchor) + div[data-testid="stElementContainer"] [data-baseweb="select"] div {
        font-size: 0.68rem !important;
        font-weight: 700 !important;
        color: var(--text-1) !important;
        -webkit-text-fill-color: var(--text-1) !important;
    }
    div.stElementContainer:has(.dimension-select-anchor) + div[data-testid="stElementContainer"] [data-baseweb="select"] svg {
        fill: var(--text-2) !important;
    }
    .hist-box {
        margin-top: 10px;
        border: 1px solid var(--border);
        border-radius: 12px;
        overflow: hidden;
        background: var(--surface-strong);
    }
    .hist-wrap {
        margin: 0;
        overflow-y: auto;
        overflow-x: hidden;
        height: var(--recent-table-height);
        scrollbar-width: thin;
        scrollbar-color: rgba(23, 21, 18, 0.22) transparent;
    }
    .hist-wrap::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    .hist-wrap::-webkit-scrollbar-track {
        background: transparent;
    }
    .hist-wrap::-webkit-scrollbar-thumb {
        background: rgba(23, 21, 18, 0.22);
        border-radius: 999px;
        border: 2px solid transparent;
        background-clip: padding-box;
    }
    .hist-wrap::-webkit-scrollbar-corner {
        background: transparent;
    }
    .hist-table {
        width: 100%;
        margin: 0;
        table-layout: fixed;
        border-collapse: collapse;
        box-sizing: border-box;
    }
    .hist-table thead,
    .hist-table tbody,
    .hist-table tr {
        margin: 0;
        padding: 0;
    }
    .hist-table thead th {
        text-align: center;
        padding: 6px 8px;
        font-size: 0.68rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--text-1);
        background: color-mix(in srgb, var(--surface-soft) 85%, var(--blue-bg));
        line-height: 1.2;
        height: 24px;
        vertical-align: middle;
        position: sticky;
        top: 0;
        z-index: 1;
        border-bottom: 1px solid var(--border);
    }
    .hist-table td {
        text-align: center;
        padding: 6px 8px;
        border-bottom: 1px solid rgba(221,215,203,0.7);
        font-size: 0.68rem;
        line-height: 1.2;
        height: 24px;
        color: var(--text-1);
        background: var(--surface-strong);
    }
    .hist-table tr:nth-child(even) td {
        background: color-mix(in srgb, var(--surface-soft) 64%, var(--surface-strong));
    }
    .hist-table tbody tr:hover td {
        background: color-mix(in srgb, var(--blue-bg) 58%, var(--surface-strong));
    }
    .hist-table tbody tr:last-child td { border-bottom: none; }
    .mono { font-family: var(--mono); color: var(--text-1); }
    .result-pass,
    .hist-table td.result-pass { color: var(--green) !important; font-weight: 800; }
    .result-fail,
    .hist-table td.result-fail { color: var(--red) !important; font-weight: 800; }
    .result-na,
    .hist-table td.result-na { color: var(--text-2) !important; font-weight: 700; }
    .hist-table td.dim-alert { color: var(--red) !important; font-weight: 800; }
    .table-pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 48px;
        padding: 2px 7px;
        border-radius: 999px;
        font-size: 0.58rem;
        font-weight: 700;
        font-family: var(--mono);
    }
    .table-pill.pass { color: var(--green); background: var(--green-bg); border: 1px solid var(--green-bd); }
    .table-pill.fail { color: var(--red); background: var(--red-bg); border: 1px solid var(--red-bd); }
    .table-pill.na { color: var(--text-2); background: var(--surface-soft); border: 1px solid var(--border); }

    [data-testid="stDataFrame"] {
        border: 0 !important;
        border-radius: 0 !important;
        overflow: visible !important;
        background: var(--surface-strong) !important;
        box-shadow: none !important;
    }
    [data-testid="stDataFrame"] [role="grid"],
    [data-testid="stDataFrame"] [role="table"],
    [data-testid="stDataFrame"] [role="row"],
    [data-testid="stDataFrame"] [role="columnheader"],
    [data-testid="stDataFrame"] [role="cell"] {
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
    }
    [data-testid="stDataFrame"] * {
        color: var(--text-1) !important;
    }
    @media (max-width: 1100px) {
        .inspection-layout,
        .chart-grid,
        .status-list,
        .stat-grid,
        .q-grid,
        .printer-grid,
        .meta-grid {
            grid-template-columns: 1fr !important;
        }
        .topbar-meta,
        .status-pill {
            justify-self: start;
        }
        .record-grid {
            grid-template-columns: 1fr;
        }
        .capture-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }
    }

    @media (max-width: 980px) {
        div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) {
            min-height: auto;
            --inspect-ctl-h: 30px;
            --inspect-ctl-font: 0.78rem;
        }
        div[data-testid="stVerticalBlock"]:has(#inspection-controls-anchor) > div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            row-gap: 0.35rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(#inspection-controls-anchor) > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            flex: 1 1 calc(50% - 0.2rem) !important;
            width: calc(50% - 0.2rem) !important;
        }
        div[data-testid="stVerticalBlock"]:has(#inspection-controls-anchor) > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child {
            flex-basis: 100% !important;
            width: 100% !important;
        }
    }

    @media (max-width: 780px) {
        :root {
            --stack-gap: 14px;
        }
        .mobile-topbar-spacer {
            display: block !important;
            height: 62px !important;
        }
        div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type {
            display: flex !important;
            flex-direction: column !important;
            align-items: stretch !important;
            flex-wrap: nowrap !important;
            gap: 12px !important;
            width: 100% !important;
            max-width: 100% !important;
            margin-top: 0 !important;
        }
        div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            max-width: 100% !important;
            display: block !important;
            min-width: 100% !important;
            margin-bottom: 0 !important;
            position: static !important;
            inset: auto !important;
            float: none !important;
        }
        [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {
            gap: 14px !important;
        }
        div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] > div:first-child:has(> .status-card),
        div[data-testid="stMainBlockContainer"] > div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] > div:first-child:has(> .card) {
            margin-top: 0 !important;
            padding-top: 0 !important;
        }
        html, body, [data-testid="stAppViewContainer"],
        [data-testid="stApp"],
        section[data-testid="stMain"],
        .block-container,
        div[data-testid="stMainBlockContainer"] {
            overflow-y: auto !important;
            height: auto !important;
            min-height: 100vh !important;
        }
        .block-container {
            padding: 8px 10px 18px !important;
        }
        .topbar {
            left: 8px !important;
            right: 58px !important;
            width: auto !important;
            max-width: none !important;
            grid-template-columns: 1fr !important;
            gap: 4px !important;
            top: 0 !important;
            padding: 6px 8px !important;
            border-radius: 0 0 12px 12px !important;
        }
        .topbar-info {
            gap: 6px !important;
            align-items: flex-start !important;
        }
        .topbar-title {
            flex-direction: column !important;
            align-items: flex-start !important;
            gap: 6px !important;
        }
        div.stElementContainer:has(.theme-floating-anchor) + div[data-testid="stElementContainer"] {
            top: 0 !important;
            right: 8px !important;
            width: 42px !important;
        }
        div.stElementContainer:has(.theme-floating-anchor) + div[data-testid="stElementContainer"] [data-testid="stButton"] {
            width: 42px !important;
        }
        div.stElementContainer:has(.theme-floating-anchor) + div[data-testid="stElementContainer"] button {
            min-width: 42px !important;
            width: 42px !important;
            height: auto !important;
            min-height: 38px !important;
            padding: 6px 6px !important;
            border-radius: 0 0 12px 12px !important;
        }
        .card,
        .status-card {
            padding: 12px;
            border-radius: 12px;
        }
        div.stElementContainer {
            margin-bottom: 12px !important;
        }
        .topbar-name {
            font-size: 0.64rem;
            white-space: normal;
            overflow: visible;
            text-overflow: clip;
            line-height: 1.15;
            word-break: break-word;
        }
        .topbar-meta,
        .status-pill {
            font-size: 0.56rem !important;
        }
        .card-title,
        .status-head {
            align-items: flex-start;
            gap: 8px;
            margin-bottom: 10px;
        }
        .card-label,
        .status-title {
            font-size: 0.82rem;
        }
        .card-note,
        .status-row-note {
            font-size: 0.72rem;
        }
        .stat-grid,
        .q-grid,
        .meta-grid,
        .printer-grid,
        .status-list,
        .chart-grid {
            grid-template-columns: 1fr !important;
            gap: 8px;
        }
        .inspection-layout {
            grid-template-columns: 1fr !important;
            grid-template-areas:
                "capture"
                "sides"
                "result"
                "detail";
            gap: 10px;
        }
        .side-grid {
            grid-template-columns: 1fr;
        }
        .capture-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            height: auto;
        }
        .insp-grid { grid-template-rows: auto auto; }
        .dim-block { min-height: 130px; }
        .record-grid { grid-template-columns: 1fr; }
        .status-row {
            padding: 3px 0;
        }
        .status-row-name {
            font-size: 0.76rem;
        }
        .printer-task-name,
        .meta-value,
        .temp-num,
        .stat-val {
            font-size: 1rem;
        }
        .q-num {
            font-size: 1.3rem;
        }
        .card-empty {
            min-height: auto !important;
            height: auto !important;
            overflow: visible !important;
        }
        .project-logo-wrap {
            margin-top: 4px !important;
            padding-top: 0 !important;
        }
        div[data-testid="stVerticalBlock"] > div:has(> .card > .project-info) {
            margin-bottom: 18px !important;
        }
        div[data-testid="stVerticalBlock"] > div:has(> .card > .q-grid) {
            margin-top: 8px !important;
        }
    }

    @media (max-width: 560px) {
        .mobile-topbar-spacer {
            height: 68px !important;
        }
        div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)) {
            --inspect-ctl-h: 32px;
            --inspect-ctl-font: 0.8rem;
        }
        div[data-testid="stVerticalBlock"]:has(#inspection-controls-anchor) > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            flex-basis: 100% !important;
            width: 100% !important;
        }
        .block-container {
            padding: 8px 8px 14px !important;
        }
        .topbar-kicker {
            font-size: 0.56rem;
        }
        .topbar-name {
            font-size: 0.6rem;
            white-space: normal;
            overflow: visible;
            text-overflow: clip;
        }
        .topbar-info {
            flex-direction: column !important;
            align-items: flex-start !important;
        }
        .card-label,
        .status-title {
            font-size: 0.76rem;
        }
        .card-note {
            font-size: 0.68rem;
        }
        .info-columns {
            grid-template-columns: 1fr;
        }
        .project-logo {
            max-height: 48px;
        }
        .capture-grid {
            grid-template-columns: 1fr;
        }
        .record-grid {
            grid-template-columns: 1fr;
        }
        .status-row {
            flex-direction: row;
            align-items: center;
        }
        .hist-wrap {
            overflow-x: hidden;
        }
        .hist-table {
            min-width: 0 !important;
            width: 100% !important;
            table-layout: fixed !important;
        }
        .hist-table thead th,
        .hist-table td {
            padding: 5px 4px !important;
            font-size: 0.6rem !important;
            line-height: 1.15 !important;
            white-space: normal !important;
            word-break: break-word !important;
            overflow-wrap: anywhere !important;
        }
        .chart-head {
            flex-direction: column;
            align-items: flex-start;
            gap: 4px;
        }
    }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<style>
    :root {{
        --bg: {theme["bg"]};
        --bg-accent: {theme["bg_accent"]};
        --surface: {theme["surface"]};
        --surface-strong: {theme["surface_strong"]};
        --surface-soft: {theme["surface_soft"]};
        --border: {theme["border"]};
        --border-strong: {theme["border_strong"]};
        --text-1: {theme["text_1"]};
        --text-2: {theme["text_2"]};
        --text-3: {theme["text_3"]};
        --green: {theme["green"]};
        --green-bg: {theme["green_bg"]};
        --green-bd: {theme["green_bd"]};
        --red: {theme["red"]};
        --red-bg: {theme["red_bg"]};
        --red-bd: {theme["red_bd"]};
        --amber: {theme["amber"]};
        --amber-bg: {theme["amber_bg"]};
        --amber-bd: {theme["amber_bd"]};
        --blue: {theme["blue"]};
        --blue-bg: {theme["blue_bg"]};
        --blue-bd: {theme["blue_bd"]};
        --shadow: {theme["shadow"]};
    }}

    [data-testid="stAppViewContainer"] {{
        background: linear-gradient(180deg, var(--bg) 0%, var(--bg-accent) 100%) !important;
    }}
    .main {{
        background: transparent !important;
    }}
    [data-testid="stSegmentedControl"], [data-testid="stSelectbox"] {{
        margin-bottom: 2px !important;
    }}
    .topbar,
    .card,
    .status-card,
    .chart-shell,
    .hist-box,
    .hist-wrap,
    .stat-box,
    .meta-box,
    .temp-box,
    .progress-wrap,
    .printer-task,
    .status-row,
    .record-panel,
    .side-item,
    .overall-box,
    .q-box {{
        background-color: var(--surface-strong) !important;
        color: var(--text-1) !important;
        border-color: var(--border) !important;
        box-shadow: var(--shadow) !important;
    }}
    div[data-testid="stVerticalBlock"]:has(#inspection-card-anchor):not(:has(div[data-testid="stVerticalBlock"] #inspection-card-anchor)),
    div[data-testid="stVerticalBlock"]:has(#recent-records-anchor):not(:has(div[data-testid="stVerticalBlock"] #recent-records-anchor)),
    div[data-testid="stVerticalBlock"]:has(#ng-chart-anchor):not(:has(div[data-testid="stVerticalBlock"] #ng-chart-anchor)),
    div[data-testid="stVerticalBlock"]:has(#trend-chart-anchor):not(:has(div[data-testid="stVerticalBlock"] #trend-chart-anchor)) {{
        background: linear-gradient(180deg, var(--surface-strong), var(--surface)) !important;
        border-color: var(--border) !important;
        box-shadow: var(--shadow) !important;
    }}
    .hist-table,
    .img-box,
    .status-row,
    .record-line {{
        background: var(--surface-soft) !important;
    }}
    .q-box.total {{
        background: linear-gradient(180deg, color-mix(in srgb, var(--bg-accent) 72%, var(--surface-strong)), color-mix(in srgb, var(--surface-soft) 88%, var(--bg-accent))) !important;
        border-color: color-mix(in srgb, var(--border-strong) 78%, var(--bg-accent)) !important;
    }}
    .q-box.pass {{
        background: linear-gradient(180deg, color-mix(in srgb, var(--green-bg) 75%, var(--surface-strong)), var(--green-bg)) !important;
        border-color: var(--green-bd) !important;
    }}
    .q-box.fail {{
        background: linear-gradient(180deg, color-mix(in srgb, var(--red-bg) 75%, var(--surface-strong)), var(--red-bg)) !important;
        border-color: var(--red-bd) !important;
    }}
    .q-box.yield {{
        background: linear-gradient(180deg, color-mix(in srgb, var(--blue-bg) 75%, var(--surface-strong)), var(--blue-bg)) !important;
        border-color: var(--blue-bd) !important;
    }}
    .bar-track,
    .mini-progress,
    .progress-track,
    .meta-box,
    .stat-box,
    .temp-box,
    .printer-task,
    .record-panel,
    .dim-block,
    .side-item,
    .overall-box,
    .hist-box,
    .hist-wrap,
    .q-box {{
        border-color: var(--border) !important;
    }}
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div,
    div[data-baseweb="popover"] > div,
    input,
    textarea {{
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
        border-color: var(--border) !important;
        -webkit-text-fill-color: var(--text-1) !important;
        caret-color: var(--text-1) !important;
    }}
    div[data-baseweb="popover"] ul,
    div[data-baseweb="popover"] li {{
        background: var(--surface-strong) !important;
        color: var(--text-1) !important;
    }}
    div[data-baseweb="select"] svg,
    [data-testid="stSelectbox"] svg,
    [data-testid="stSegmentedControl"] svg {{
        fill: var(--text-2) !important;
    }}
    .hist-table th,
    .hist-table td,
    .hist-table tr,
    .record-line span,
    .record-col-title,
    .overall-head,
    .overall-value,
    .q-sub,
    .status-row-note,
    .status-row-name span,
    .meta-label,
    .meta-value,
    .stat-lbl,
    .stat-sub,
    .temp-lbl,
    .progress-label,
    .progress-value,
    .card-note,
    .topbar-kicker,
    .topbar-name,
    .topbar-meta,
    .chart-title,
    .chart-sub {{
        color: var(--text-1) !important;
    }}
    .topbar-meta,
    .card-note,
    .stat-sub,
    .meta-label,
    .temp-lbl,
    .q-sub,
    .chart-sub,
    .hist-table th,
    .status-row-note {{
        color: var(--text-2) !important;
    }}
    .hist-table thead th {{
        background: {"color-mix(in srgb, var(--blue-bg) 34%, var(--surface-soft))" if theme_mode == "☾" else "color-mix(in srgb, var(--surface-soft) 85%, var(--blue-bg))"} !important;
        border-bottom-color: {"color-mix(in srgb, var(--blue-bd) 58%, var(--border))" if theme_mode == "☾" else "var(--border)"} !important;
        box-shadow: {"inset 0 -1px 0 color-mix(in srgb, var(--blue-bd) 32%, transparent)" if theme_mode == "☾" else "none"} !important;
        color: {"var(--text-1)" if theme_mode == "☾" else "var(--text-2)"} !important;
        letter-spacing: 0.12em !important;
        font-weight: 800 !important;
    }}
    .hist-wrap {{
        background: var(--surface-strong) !important;
        scrollbar-color: {"rgba(178, 190, 202, 0.34) transparent" if theme_mode == "☾" else "rgba(23, 21, 18, 0.22) transparent"} !important;
        scrollbar-gutter: auto !important;
    }}
    .hist-wrap::-webkit-scrollbar-thumb {{
        background: {"rgba(178, 190, 202, 0.34)" if theme_mode == "☾" else "rgba(23, 21, 18, 0.22)"} !important;
    }}
    .hist-table td {{
        background: {"color-mix(in srgb, var(--surface-strong) 96%, var(--surface-soft))" if theme_mode == "☾" else "var(--surface-strong)"} !important;
        border-bottom-color: {"color-mix(in srgb, var(--border) 72%, transparent)" if theme_mode == "☾" else "rgba(221,215,203,0.7)"} !important;
    }}
    .hist-table tr:nth-child(even) td {{
        background: {"color-mix(in srgb, var(--surface-soft) 92%, var(--surface-strong))" if theme_mode == "☾" else "color-mix(in srgb, var(--surface-soft) 64%, var(--surface-strong))"} !important;
    }}
    .hist-table tbody tr:hover td {{
        background: {"color-mix(in srgb, var(--blue-bg) 42%, var(--surface-strong))" if theme_mode == "☾" else "color-mix(in srgb, var(--blue-bg) 58%, var(--surface-strong))"} !important;
    }}
    .record-panel {{
        background: transparent !important;
        box-shadow: none !important;
        border: 0 !important;
    }}
    .progress-wrap {{
        background: transparent !important;
        box-shadow: none !important;
        border: 0 !important;
    }}
    .status-row {{
        background: color-mix(in srgb, var(--surface-soft) 72%, transparent) !important;
        border: 1px solid color-mix(in srgb, var(--border) 88%, transparent) !important;
        border-radius: 10px !important;
        padding: 8px 10px !important;
        box-shadow: none !important;
    }}
    .info-panel {{
        background: {"linear-gradient(180deg, color-mix(in srgb, var(--surface-soft) 92%, var(--surface-strong)), color-mix(in srgb, var(--bg-accent) 28%, var(--surface-strong)))" if theme_mode == "☾" else "linear-gradient(180deg, color-mix(in srgb, var(--bg-accent) 52%, var(--surface-strong)), color-mix(in srgb, var(--surface-soft) 82%, var(--bg-accent)))"} !important;
        border-color: {"color-mix(in srgb, var(--border-strong) 86%, transparent)" if theme_mode == "☾" else "var(--border-strong)"} !important;
    }}
    .info-kicker,
    .info-label {{
        color: {"var(--text-2)" if theme_mode == "☾" else "#5f543f"} !important;
    }}
    .info-body,
    .info-value,
    .info-value strong {{
        color: {"var(--text-1)" if theme_mode == "☾" else "#201c16"} !important;
    }}
    .record-col {{
        background: transparent !important;
        border-color: {"color-mix(in srgb, var(--border) 52%, transparent)" if theme_mode == "☾" else "color-mix(in srgb, var(--border) 62%, transparent)"} !important;
    }}
    .progress-track {{
        background: transparent !important;
        border-color: {"color-mix(in srgb, var(--border) 48%, transparent)" if theme_mode == "☾" else "color-mix(in srgb, var(--border) 58%, transparent)"} !important;
        box-shadow: none !important;
    }}
    .record-line {{
        background: transparent !important;
    }}
    .side-item.good {{
        background: color-mix(in srgb, var(--green-bg) 72%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--green-bd) 88%, transparent) !important;
    }}
    .side-item.ng {{
        background: color-mix(in srgb, var(--red-bg) 72%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--red-bd) 88%, transparent) !important;
    }}
    .badge-good,
    .table-pill.pass {{
        color: var(--green) !important;
        background: color-mix(in srgb, var(--green-bg) 68%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--green-bd) 90%, transparent) !important;
    }}
    .badge-ng,
    .table-pill.fail {{
        color: var(--red) !important;
        background: color-mix(in srgb, var(--red-bg) 68%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--red-bd) 90%, transparent) !important;
    }}
    .badge-neutral,
    .table-pill.na {{
        color: var(--text-2) !important;
        background: color-mix(in srgb, var(--surface-soft) 86%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--border) 92%, transparent) !important;
    }}
    .overall-pass,
    .q-num.green,
    .side-item.good .side-name {{
        color: var(--green) !important;
    }}
    .overall-fail,
    .q-num.red,
    .record-val.defect,
    .side-item.ng .side-name {{
        color: var(--red) !important;
    }}
    .overall-neutral,
    .q-num,
    .q-sub {{
        color: var(--text-1) !important;
    }}
    .overall-box {{
        background: color-mix(in srgb, var(--surface-soft) 82%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--border) 92%, transparent) !important;
    }}
    .overall-box.overall-pass {{
        background: color-mix(in srgb, var(--green-bg) 72%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--green-bd) 88%, transparent) !important;
    }}
    .overall-box.overall-fail {{
        background: color-mix(in srgb, var(--red-bg) 72%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--red-bd) 88%, transparent) !important;
    }}
    .overall-box.overall-neutral {{
        background: color-mix(in srgb, var(--surface-soft) 86%, var(--surface-strong)) !important;
        border-color: color-mix(in srgb, var(--border) 92%, transparent) !important;
    }}
    .overall-head {{
        color: var(--text-2) !important;
    }}
    .overall-value {{
        color: inherit !important;
    }}
    .q-sub {{
        color: var(--text-2) !important;
    }}
    .result-pass {{ color: var(--green) !important; }}
    .result-fail {{ color: var(--red) !important; }}
    .result-na {{ color: var(--text-2) !important; }}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def get_requests_session():
    session = requests.Session()
    session.headers.update({"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    return session


@st.cache_data(show_spinner=False)
def fetch(table, limit=20, order="timestamp", cache_bucket=0):
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*&order={order}.desc"
    if limit is not None:
        url += f"&limit={limit}"
    try:
        response = get_requests_session().get(url, timeout=SUPABASE_TIMEOUT_SECONDS)
        if response.status_code == 200:
            rows = response.json()
            print(
                f"[DASH_FETCH] table={table} status=200 rows={len(rows) if isinstance(rows, list) else 'n/a'}",
                flush=True,
            )
            return pd.DataFrame(rows)
        print(f"[DASH_FETCH] table={table} status={response.status_code} body={response.text[:240]}", flush=True)
    except Exception:
        import traceback
        print(f"[DASH_FETCH] table={table} exception", flush=True)
        traceback.print_exc()
    return pd.DataFrame()


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_timestamp(value):
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def is_timestamp_fresh(value, max_age_seconds, now_utc=None):
    parsed = parse_timestamp(value)
    if parsed is None:
        return False

    current = now_utc or datetime.now(timezone.utc)
    age_seconds = (current - parsed).total_seconds()
    return age_seconds <= max_age_seconds and age_seconds >= -300


def normalize_status(value):
    return str(value).strip().upper() if value is not None else "N/A"


def normalize_result_value(value):
    text = normalize_status(value)
    if text in {"PASS", "GOOD"}:
        return "PASS"
    if text in {"FAIL", "NG", "BAD"}:
        return "FAIL"
    return text


def dimension_in_spec(value, key):
    spec = DIMENSION_TARGETS.get(str(key).strip().lower())
    if not spec:
        return None
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() == "nan" or text == "-":
        return None
    if text.lower().endswith(" mm"):
        text = text[:-3].strip()

    try:
        numeric_value = float(text)
    except (TypeError, ValueError):
        return None

    lower, upper = spec
    return lower <= numeric_value <= upper


def dimension_alert_class(value, key):
    return "dim-alert" if dimension_in_spec(value, key) is False else ""


def preprocess_part_records(df):
    if df.empty:
        return df.copy()

    processed = df.copy()
    if "record_timestamp" in processed.columns:
        processed["_dt"] = pd.to_datetime(processed["record_timestamp"], errors="coerce")
    else:
        processed["_dt"] = pd.NaT

    if "part_id" in processed.columns:
        processed["_part"] = processed["part_id"].astype(str).str.strip()
    else:
        processed["_part"] = ""

    if "result" in processed.columns:
        result_norm = processed["result"].astype(str).str.strip().str.upper()
        processed["_result_norm"] = result_norm.replace({"GOOD": "PASS", "NG": "FAIL", "BAD": "FAIL"})
    else:
        processed["_result_norm"] = ""

    processed = processed.sort_values("_dt", ascending=False, na_position="last")
    processed["_date_text"] = processed["_dt"].dt.strftime("%Y-%m-%d").fillna("")
    timestamp_text = processed["_dt"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("N/A")
    part_text = processed.get("part_id", pd.Series("—", index=processed.index)).fillna("—").astype(str)
    processed["_match_label"] = timestamp_text + " | PART #" + part_text

    return processed


def metric_tone(value, warn=70, bad=85):
    if value >= bad:
        return "tone-bad"
    if value >= warn:
        return "tone-warn"
    return "tone-good"


def status_tone(value):
    text = str(value).strip().lower()
    if text in {"connected", "online", "idle", "ready", "printing", "finish", "pass", "good", "active"}:
        return "good"
    if text in {"unknown", "busy", "warning", "heatbed_preheating"}:
        return "warn"
    return "bad"


def status_dot(value):
    tone = status_tone(value)
    return {"good": "dot-on", "warn": "dot-warn", "bad": "dot-off"}[tone]


def format_timestamp(value):
    if not value or value == "nan":
        return "N/A"
    raw = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(raw[:26], fmt)
            return dt.strftime("%d/%m/%y %H:%M")
        except ValueError:
            continue
    return raw[:16]


def format_remaining_minutes(value):
    minutes = int(safe_float(value, 0))
    if minutes <= 0:
        return "N/A"
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def result_badge(value):
    result = normalize_status(value)
    if result in {"PASS", "GOOD"}:
        return "table-pill pass"
    if result in {"FAIL", "NG", "BAD"}:
        return "table-pill fail"
    return "table-pill na"


def side_status_tone(value):
    text = normalize_status(value)
    if text.startswith("GOOD"):
        return "good"
    if text.startswith("NG"):
        return "ng"
    return "neutral"


def build_history_frame(df):
    if df.empty:
        return pd.DataFrame([{"Time": "N/A", "Part": "—", "Result": "N/A"}])

    history_df = df.head(20).copy()
    history_df["Time"] = history_df.get("record_timestamp", pd.Series(dtype=object)).map(format_timestamp)
    history_df["Part"] = "#" + history_df.get("part_id", pd.Series(dtype=object)).fillna("—").astype(str)
    if "_result_norm" in history_df.columns:
        history_df["Result"] = history_df["_result_norm"].fillna("").replace("", "N/A")
    else:
        history_df["Result"] = history_df.get("result", pd.Series(dtype=object)).map(normalize_result_value)
    return history_df[["Time", "Part", "Result"]]


@st.cache_data(show_spinner=False)
def render_history_table(df):
    history_df = build_history_frame(df).head(HISTORY_ROWS_RENDER_LIMIT)
    rows_html = []
    for _, row in history_df.iterrows():
        time_text = html.escape(str(row.get("Time", "N/A")))
        part_text = html.escape(str(row.get("Part", "—")))
        result_raw = str(row.get("Result", "N/A"))
        result_norm = normalize_result_value(result_raw)
        result_text = html.escape(result_norm)
        if result_norm == "PASS":
            result_class = "result-pass"
        elif result_norm in {"FAIL", "NG"}:
            result_class = "result-fail"
        else:
            result_class = "result-na"
        rows_html.append(
            f"<tr><td class=\"mono\">{time_text}</td><td class=\"mono\">{part_text}</td><td class=\"mono {result_class}\">{result_text}</td></tr>"
        )

    return (
        "<div class=\"hist-box\">"
        "<div class=\"hist-wrap\">"
        "<table class=\"hist-table\">"
        "<colgroup><col style=\"width:38%\"><col style=\"width:26%\"><col style=\"width:36%\"></colgroup>"
        "<thead><tr><th>Time</th><th>Part</th><th>Result</th></tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
        "</div>"
        "</div>"
    )


def pick_first_value(row, keys, default="-"):
    if row is None:
        return default
    for key in keys:
        value = row.get(key) if hasattr(row, "get") else None
        if value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() == "nan":
            continue
        return value
    return default


def format_dimension_value(value):
    if value is None:
        return "-"
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return "-"
    try:
        return f"{float(text):.3f} mm"
    except ValueError:
        return text


def normalize_defect_label(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "n/a", "good", "pass", "ok"}:
        return ""
    text = text.replace("DEFECT_", "").replace("defect_", "")
    text = text.replace("_", " ").strip()
    return text.title()


def canonical_defect_label(value):
    label = normalize_defect_label(value)
    if not label:
        return ""
    normalized = label.lower().replace(" ", "")
    if normalized in {"scratches", "scratch"}:
        return "Scratches"
    if normalized == "hole":
        return "Hole"
    if normalized == "scrap":
        return "Scrap"
    return "Other"


def record_to_inspection_fields(row):
    if row is None:
        return {
            "part_id": "—",
            "side1": "N/A",
            "side2": "N/A",
            "side3": "N/A",
            "defect_s1": "-",
            "defect_s2": "-",
            "defect_s3": "-",
            "capture_s1": "",
            "capture_s2": "",
            "capture_s3": "",
            "dim_top": "-",
            "dim_bottom": "-",
            "dim_length": "-",
            "result": "N/A",
            "record_ts": "N/A",
        }

    defect_s1_raw = pick_first_value(row, ["defect_s1", "defect _s1"], "-")
    defect_s2_raw = pick_first_value(row, ["defect_s2", "defect _s2"], "-")
    defect_s3_raw = pick_first_value(row, ["defect_s3", "defect _s3"], "-")
    dim_top_raw = pick_first_value(row, ["dimension of top", "dim_top", "top", "dimension_top", "top_mm", "top_value"], "-")
    dim_bottom_raw = pick_first_value(row, ["dimension of bottom", "dim_bottom", "bottom", "dimension_bottom", "bottom_mm", "bottom_value"], "-")
    dim_length_raw = pick_first_value(row, ["dimension of length", "dim_length", "length", "dimension_length", "length_mm", "length_value"], "-")

    return {
        "part_id": row.get("part_id", "—"),
        "side1": normalize_status(row.get("side1", "N/A")),
        "side2": normalize_status(row.get("side2", "N/A")),
        "side3": normalize_status(row.get("side3", "N/A")),
        "defect_s1": str(defect_s1_raw),
        "defect_s2": str(defect_s2_raw),
        "defect_s3": str(defect_s3_raw),
        "capture_s1": str(row.get("capture_s1", "") or ""),
        "capture_s2": str(row.get("capture_s2", "") or ""),
        "capture_s3": str(row.get("capture_s3", "") or ""),
        "dim_top": format_dimension_value(dim_top_raw),
        "dim_bottom": format_dimension_value(dim_bottom_raw),
        "dim_length": format_dimension_value(dim_length_raw),
        "result": normalize_result_value(row.get("result", "N/A")),
        "record_ts": format_timestamp(row.get("record_timestamp", "")),
    }

def render_capture_cell(image_url, side_no):
    side_label = f"Side {side_no}"
    if image_url:
        safe_url = html.escape(str(image_url), quote=True)
        modal_id = f"capture-gallery-side-{int(side_no)}"
        return (
            f'<div class="img-box has-image">'
            f'<img src="{safe_url}" alt="{side_label} capture">'
            f'<a class="img-hitbox" href="#{modal_id}" aria-label="Open {side_label} image"></a>'
            f'<div class="img-caption"><span>Capture</span><b>{side_label}</b></div>'
            f'</div>'
        )
    return f'<div class="img-box"><span>Capture</span><b>{side_label}</b></div>'


def render_capture_gallery_modals(capture_urls):
    available_sides = [side for side in (1, 2, 3) if capture_urls.get(side)]
    if not available_sides:
        return ""

    modal_html = []
    for side in available_sides:
        safe_url = html.escape(str(capture_urls[side]), quote=True)
        modal_id = f"capture-gallery-side-{side}"
        modal_html.append(
            f'<div id="{modal_id}" class="capture-gallery-modal">'
            f'<a class="capture-gallery-backdrop" href="#" aria-label="Close image"></a>'
            f'<div class="capture-gallery-panel">'
            f'<div class="capture-gallery-head">'
            f'<div>'
            f'<div class="capture-gallery-title">Inspection Capture</div>'
            f'<div class="capture-gallery-stage">Side {side}</div>'
            f'</div>'
            f'<a class="capture-gallery-x" href="#" aria-label="Close">x</a>'
            f'</div>'
            f'<div class="capture-gallery-body">'
            f'<img src="{safe_url}" alt="Side {side} full capture">'
            f'</div>'
            f'</div>'
            f'</div>'
        )
    return "".join(modal_html)


def create_pi_combined_chart(temp, temp_hist, color):
    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "indicator"}, {"type": "scatter"}]],
        column_widths=[0.38, 0.62],
        horizontal_spacing=0.05,
    )
    fig.add_trace(
        go.Indicator(
            mode="gauge",
            value=temp,
            gauge={
                "axis": {"range": [0, 100], "visible": False},
                "bar": {"color": color, "thickness": 0.58},
                "bgcolor": "#ebe6dc",
                "borderwidth": 0,
            },
            domain={"x": [0, 0.35], "y": [0.2, 0.9]},
        ),
        row=1,
        col=1,
    )
    fill_color = f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.12)"
    fig.add_trace(
        go.Scatter(
            y=temp_hist,
            mode="lines+markers",
            line=dict(color=color, width=2.5),
            marker=dict(size=5, color=color),
            fill="tozeroy",
            fillcolor=fill_color,
        ),
        row=1,
        col=2,
    )
    fig.add_annotation(
        text="CPU TEMP",
        x=0.16,
        y=0.98,
        showarrow=False,
        font=dict(size=9, color="#8d867b"),
        xanchor="center",
    )
    fig.add_annotation(
        text=f"<b>{temp:.1f}°C</b>",
        x=0.16,
        y=0.12,
        showarrow=False,
        font=dict(size=18, color=color, family="IBM Plex Mono"),
        xanchor="center",
    )
    fig.add_annotation(
        text="15-SAMPLE TREND",
        x=0.74,
        y=0.98,
        showarrow=False,
        font=dict(size=9, color="#8d867b"),
        xanchor="center",
    )
    fig.update_xaxes(visible=False, row=1, col=2)
    fig.update_yaxes(visible=False, row=1, col=2)
    fig.update_layout(
        margin=dict(t=10, b=10, l=8, r=8),
        height=156,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def build_defect_counts(df):
    defect_columns = [col for col in ["defect_s1", "defect_s2", "defect_s3", "defect _s1", "defect _s2", "defect _s3"] if col in df.columns]
    counts = Counter()
    for col in defect_columns:
        for raw_value in df[col].dropna().tolist():
            defect_label = canonical_defect_label(raw_value)
            if defect_label:
                counts[defect_label] += 1

    if not counts:
        return (("No Defect Data", 0, 0.0),)

    preferred_order = {"Scratches": 0, "Hole": 1, "Scrap": 2, "Other": 3}
    total = sum(counts.values())
    running = 0
    rows = []
    for label, count in sorted(counts.items(), key=lambda item: (preferred_order.get(item[0], 99), -item[1], item[0])):
        running += count
        rows.append((label, count, (running / total) * 100))
    return tuple(rows)


def build_side_defect_counts(df):
    side_columns = (
        ("Side 1", ["defect_s1", "defect _s1"]),
        ("Side 2", ["defect_s2", "defect _s2"]),
        ("Side 3", ["defect_s3", "defect _s3"]),
    )
    rows = []
    for label, candidates in side_columns:
        count = 0
        for col in candidates:
            if col not in df.columns:
                continue
            for raw_value in df[col].dropna().tolist():
                if canonical_defect_label(raw_value):
                    count += 1
        rows.append((label, count))
    return tuple(rows)


@st.cache_data(show_spinner=False)
def ng_pareto_chart(defect_rows, theme_mode):
    labels = [row[0] for row in defect_rows]
    counts = [row[1] for row in defect_rows]
    cumulative = [row[2] for row in defect_rows]
    max_count = max(counts) if counts else 1
    is_dark = is_dark_theme(theme_mode)
    if is_dark:
        bar_colors = ["#5ea2e8", "#efaf63", "#7fc58f", "#c59bcf"][: len(labels)]
        bar_line_color = "rgba(255,255,255,0.16)"
        text_inside_color = "#10161d"
        cumulative_line_color = "#d9d2ff"
        cumulative_marker_fill = "#27303a"
        hover_bg = "#212933"
        hover_border = "#49586a"
        hover_text = "#eef3f7"
        axis_text = "#d7e0e8"
        percent_text = "#d9d2ff"
        grid_color = "rgba(132, 151, 172, 0.22)"
    else:
        bar_colors = ["#6fa8dc", "#f6b26b", "#93c47d", "#d5a6bd"][: len(labels)]
        bar_line_color = "rgba(255,255,255,0.82)"
        text_inside_color = "#fffdf9"
        cumulative_line_color = "#7b6fd6"
        cumulative_marker_fill = "#fffaf6"
        hover_bg = "#fffdf8"
        hover_border = "#d9cfbf"
        hover_text = "#171512"
        axis_text = "#3f3932"
        percent_text = "#5f52bf"
        grid_color = "rgba(188, 176, 160, 0.28)"
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=counts,
                marker=dict(
                    color=bar_colors,
                    line=dict(color=bar_line_color, width=1.1),
                ),
                text=counts,
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(size=12, color=text_inside_color, family="IBM Plex Mono"),
                hovertemplate="<b>%{x}</b><br>Count: %{y}<extra></extra>",
                name="Defect Count",
                width=0.58,
            ),
            go.Scatter(
                x=labels,
                y=cumulative,
                mode="lines+markers",
                line=dict(color=cumulative_line_color, width=2.2, shape="spline", smoothing=0.65),
                marker=dict(size=8, color=cumulative_marker_fill, line=dict(color=cumulative_line_color, width=1.8)),
                hovertemplate="<b>%{x}</b><br>Cumulative: %{y:.1f}%<extra></extra>",
                yaxis="y2",
                name="Cumulative %",
                cliponaxis=False,
            ),
        ]
    )
    fig.update_layout(
        margin=dict(t=18, b=10, l=8, r=8),
        height=252,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.34,
        barcornerradius=10,
        hoverlabel=dict(bgcolor=hover_bg, bordercolor=hover_border, font=dict(color=hover_text)),
        yaxis=dict(
            title=dict(text="Count", font=dict(size=11, color=axis_text)),
            range=[0, max_count],
            tickfont=dict(size=10, color=axis_text),
            gridcolor=grid_color,
            zeroline=False,
        ),
        yaxis2=dict(
            range=[0, 103],
            overlaying="y",
            side="right",
            showgrid=False,
            ticksuffix="%",
            tickfont=dict(size=10, color=percent_text),
        ),
        xaxis=dict(
            tickfont=dict(size=11, color=axis_text),
            showgrid=False,
            zeroline=False,
        ),
    )
    return fig


@st.cache_data(show_spinner=False)
def defect_by_side_chart(side_rows, theme_mode):
    labels = [row[0] for row in side_rows]
    counts = [row[1] for row in side_rows]
    max_count = max(counts) if counts else 1
    is_dark = is_dark_theme(theme_mode)
    bar_colors = ["#5ea2e8", "#efaf63", "#7fc58f"] if is_dark else ["#6fa8dc", "#f6b26b", "#93c47d"]
    axis_text = "#d7e0e8" if is_dark else "#3f3932"
    grid_color = "rgba(132, 151, 172, 0.22)" if is_dark else "rgba(188, 176, 160, 0.28)"
    hover_bg = "#212933" if is_dark else "#fffdf8"
    hover_border = "#49586a" if is_dark else "#d9cfbf"
    hover_text = "#eef3f7" if is_dark else "#171512"
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=counts,
                marker=dict(
                    color=bar_colors[: len(labels)],
                    line=dict(color="rgba(255,255,255,0.24)" if is_dark else "rgba(255,255,255,0.82)", width=1.1),
                ),
                text=counts,
                textposition="outside",
                textfont=dict(size=12, color=axis_text, family="IBM Plex Mono"),
                hovertemplate="<b>%{x}</b><br>Defects: %{y}<extra></extra>",
                width=0.52,
            )
        ]
    )
    fig.update_layout(
        margin=dict(t=18, b=10, l=8, r=8),
        height=252,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.42,
        barcornerradius=10,
        hoverlabel=dict(bgcolor=hover_bg, bordercolor=hover_border, font=dict(color=hover_text)),
        yaxis=dict(
            title=dict(text="Defect Count", font=dict(size=11, color=axis_text)),
            range=[0, max(max_count, 1) * 1.2],
            tickfont=dict(size=10, color=axis_text),
            gridcolor=grid_color,
            zeroline=False,
        ),
        xaxis=dict(
            tickfont=dict(size=11, color=axis_text),
            showgrid=False,
            zeroline=False,
        ),
    )
    return fig


@st.cache_data(show_spinner=False)
def control_chart(labels, values, theme_mode):
    is_dark = is_dark_theme(theme_mode)
    line_color = "#8eb8ff" if is_dark else "#2458a6"
    pass_color = "#70d69d" if is_dark else "#1d7a4f"
    fail_color = "#f08b81" if is_dark else "#ba4335"
    axis_text = "#d7e0e8" if is_dark else "#5a564f"
    grid_color = "rgba(132, 151, 172, 0.22)" if is_dark else "rgba(200,192,179,0.35)"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers",
            line=dict(color=line_color, width=2.5),
            marker=dict(size=8, color=[pass_color if val == 1 else fail_color for val in values]),
        )
    )
    fig.update_layout(
        margin=dict(t=10, b=16, l=0, r=0),
        height=252,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(
            range=[-0.15, 1.15],
            tickvals=[0, 1],
            ticktext=["FAIL", "PASS"],
            gridcolor=grid_color,
            tickfont=dict(size=10, color=axis_text),
        ),
        xaxis=dict(tickfont=dict(size=11, color=axis_text)),
    )
    return fig


def extract_dimension_chart_points(df, dimension_key, limit=12):
    config = DIMENSION_CHART_FIELDS.get(str(dimension_key).strip().lower())
    if df.empty or not config:
        return [], []

    recent = df.head(limit).iloc[::-1]
    labels = []
    values = []
    for _, row in recent.iterrows():
        raw_value = pick_first_value(row, config["keys"], None)
        if raw_value is None:
            continue
        try:
            numeric_value = float(str(raw_value).replace(" mm", "").strip())
        except (TypeError, ValueError):
            continue
        labels.append(str(row.get("part_id", len(labels) + 1)))
        values.append(numeric_value)
    return labels, values


@st.cache_data(show_spinner=False)
def dimension_control_chart(labels, values, theme_mode, dimension_key):
    labels = list(labels)
    values = list(values)
    is_dark = is_dark_theme(theme_mode)
    axis_text = "#d7e0e8" if is_dark else "#5a564f"
    grid_color = "rgba(132, 151, 172, 0.22)" if is_dark else "rgba(200,192,179,0.35)"
    plot_line = "#8eb8ff" if is_dark else "#2458a6"
    cl_color = "#f0be74" if is_dark else "#af650f"
    limit_color = "#f08b81" if is_dark else "#ba4335"
    hover_bg = "#212933" if is_dark else "#fffdf8"
    hover_border = "#49586a" if is_dark else "#d9cfbf"
    hover_text = "#eef3f7" if is_dark else "#171512"
    annotation_bg = "rgba(24, 28, 34, 0.78)" if is_dark else "rgba(255, 253, 248, 0.92)"

    spec_key = str(dimension_key).strip().lower()
    lower, upper = DIMENSION_TARGETS.get(spec_key, (0.0, 1.0))
    center = (lower + upper) / 2

    if values:
        y_min = min(values + [lower, center, upper])
        y_max = max(values + [lower, center, upper])
    else:
        y_min = lower
        y_max = upper

    pad = max((y_max - y_min) * 0.12, 0.004)
    y_range = [y_min - pad, y_max + pad]
    marker_colors = [plot_line if lower <= value <= upper else limit_color for value in values]

    fig = go.Figure()
    if values:
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=values,
                mode="lines+markers",
                name="Measurement",
                line=dict(color=plot_line, width=2.6),
                marker=dict(size=8, color=marker_colors, line=dict(color="rgba(255,255,255,0.78)", width=0.9)),
                hovertemplate="<b>Part %{x}</b><br>Value: %{y:.3f} mm<extra></extra>",
            )
        )

    for line_name, line_value, line_color, line_dash in (
        ("UCL", upper, limit_color, "dash"),
        ("CL", center, cl_color, "dot"),
        ("LCL", lower, limit_color, "dash"),
    ):
        fig.add_trace(
            go.Scatter(
                x=labels if labels else [""],
                y=[line_value] * (len(labels) if labels else 1),
                mode="lines",
                name=line_name,
                line=dict(color=line_color, width=1.7, dash=line_dash),
                hovertemplate=f"{line_name}: {line_value:.3f} mm<extra></extra>",
            )
        )

    if not values:
        fig.add_annotation(
            text="No dimension data available",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(size=12, color=axis_text),
        )

    fig.update_layout(
        margin=dict(t=0, b=28, l=0, r=0),
        height=252,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor=hover_bg, bordercolor=hover_border, font=dict(color=hover_text)),
        showlegend=False,
        yaxis=dict(
            title=dict(text="mm", font=dict(size=11, color=axis_text)),
            range=y_range,
            tickformat=".3f",
            gridcolor=grid_color,
            tickfont=dict(size=10, color=axis_text),
            zeroline=False,
        ),
        xaxis=dict(
            title=dict(text="Part ID", font=dict(size=11, color=axis_text), standoff=6),
            type="category",
            tickmode="array",
            tickvals=labels,
            ticktext=labels,
            tickfont=dict(size=11, color=axis_text),
            showgrid=False,
            zeroline=False,
            automargin=True,
        ),
    )

    for label_text, y_value, label_color in (
        ("UCL", upper, limit_color),
        ("CL", center, cl_color),
        ("LCL", lower, limit_color),
    ):
        fig.add_annotation(
            x=0.985,
            xref="paper",
            y=y_value,
            yref="y",
            text=label_text,
            showarrow=False,
            xanchor="right",
            yanchor="middle",
            font=dict(size=10, color=label_color, family="IBM Plex Mono"),
            bgcolor=annotation_bg,
            bordercolor="rgba(0,0,0,0)",
            borderpad=2,
        )
    return fig


st.markdown('<div id="main-columns-anchor"></div>', unsafe_allow_html=True)
st.markdown('<div class="mobile-topbar-spacer"></div>', unsafe_allow_html=True)
try:
    col_l, col_r = st.columns([0.58, 1.72], gap="medium", vertical_alignment="top")
except TypeError:
    col_l, col_r = st.columns([0.58, 1.72], gap="medium")
with col_l:
    co_slot = st.empty()
    pi_slot = st.empty()
    pr_slot = st.empty()
    extra_left_slot = st.empty()
with col_r:
    quality_slot = st.empty()
    inspection_slot = st.empty()
    try:
        ng_chart_col, trend_chart_col, history_col = st.columns([1.15, 1.15, 0.7], gap="medium", vertical_alignment="top")
    except TypeError:
        ng_chart_col, trend_chart_col, history_col = st.columns([1.15, 1.15, 0.7], gap="medium")
    with ng_chart_col:
        ng_chart_slot = st.empty()
    with trend_chart_col:
        trend_chart_slot = st.empty()
    with history_col:
        history_slot = st.empty()

topbar_slot = st.empty()
theme_switch_slot = st.empty()
gallery_slot = st.empty()
clock_script_slot = st.empty()

temp_history = [55.0] * 15

# Streamlit should render in single-pass mode; avoid blocking loops that cause UI lag.
if True:
    now = datetime.now()
    now_utc = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    last_sys_refresh_ts = st.session_state.get("_dash_last_sys_refresh_ts", 0.0)
    last_parts_refresh_ts = st.session_state.get("_dash_last_parts_refresh_ts", 0.0)
    needs_sys_refresh = (now_ts - last_sys_refresh_ts) >= SYSTEM_REFRESH_SECONDS
    needs_parts_refresh = (now_ts - last_parts_refresh_ts) >= PART_RECORDS_REFRESH_SECONDS

    if needs_sys_refresh or "_dash_df_sys" not in st.session_state:
        sys_cache_bucket = int(now_ts // SYSTEM_REFRESH_SECONDS)
        st.session_state["_dash_df_sys"] = fetch("system_status", limit=1, order="id", cache_bucket=sys_cache_bucket)
        st.session_state["_dash_last_sys_refresh_ts"] = now_ts

    if needs_parts_refresh or "_dash_df_parts" not in st.session_state:
        parts_cache_bucket = int(now_ts // PART_RECORDS_REFRESH_SECONDS)
        st.session_state["_dash_df_parts"] = fetch(
            "part_records",
            limit=PART_RECORDS_FETCH_LIMIT,
            order="record_timestamp",
            cache_bucket=parts_cache_bucket,
        )
        st.session_state["_dash_df_parts_search"] = preprocess_part_records(st.session_state["_dash_df_parts"])
        st.session_state["_dash_last_parts_refresh_ts"] = now_ts

    df_sys = st.session_state.get("_dash_df_sys", pd.DataFrame())
    df_parts = st.session_state.get("_dash_df_parts", pd.DataFrame())
    df_parts_search_base = st.session_state.get("_dash_df_parts_search", df_parts.copy())
    print(
        f"[DASH_STATE] df_sys_rows={len(df_sys)} df_sys_cols={list(df_sys.columns)} "
        f"df_parts_rows={len(df_parts)} df_parts_cols={list(df_parts.columns)}",
        flush=True,
    )

    cpu = ram = disk = None
    temp = None
    active = False
    raspberry_online = False
    nozzle = bed = None
    printer_status = None
    printer_progress = None
    printer_task = None
    printer_remaining = None
    printer_stage = None
    robot_status = "Unknown"
    sys_timestamp = ""
    server_ip = "127.0.0.1"
    modbus_port = "5020"

    if not df_sys.empty:
        latest = df_sys.iloc[0]
        cpu = safe_float(latest.get("pi_cpu_usage"), None)
        ram = safe_float(latest.get("pi_ram_usage"), None)
        disk = safe_float(latest.get("pi_disk_usage"), None)
        temp = safe_float(latest.get("pi_cpu_temp"), None)
        printer_status = latest.get("printer_status")
        robot_status = latest.get("robot_status", "Unknown")
        printer_progress = safe_float(latest.get("printer_progress"), None)
        printer_task = str(latest.get("printer_task_name") or "").strip() or None
        printer_stage = str(latest.get("printer_sub_stage") or "").strip() or None
        printer_remaining_raw = latest.get("printer_remaining_time")
        printer_remaining_fmt = format_remaining_minutes(printer_remaining_raw)
        printer_remaining = printer_remaining_fmt if printer_remaining_fmt != "N/A" else None
        server_ip = str(latest.get("server_ip") or server_ip)
        modbus_port = str(latest.get("modbus_port") or modbus_port)
        sys_timestamp = str(latest.get("timestamp", ""))
        nozzle = safe_float(latest.get("printer_nozzle_temp"), None)
        bed = safe_float(latest.get("printer_bed_temp"), None)

    system_status_is_fresh = is_timestamp_fresh(sys_timestamp, SYSTEM_STATUS_STALE_SECONDS, now_utc)

    if not system_status_is_fresh:
        cpu = None
        ram = None
        disk = None
        temp = None
        nozzle = None
        bed = None
        printer_progress = None
        printer_task = None
        printer_remaining = None
        printer_stage = None
        printer_status = "Disconnected"
        if not robot_status:
            robot_status = "Disconnected"

    printer_status_upper = str(printer_status or "").strip().upper()
    printer_is_active = printer_status_upper in {"RUNNING", "PRINTING", "PREPARE", "PREPARING", "PAUSE", "PAUSED"} or (printer_progress or 0) > 0
    printer_connected = (
        system_status_is_fresh
        and printer_status_upper not in {"DISCONNECTED", "UNKNOWN", "", "STALE", "CONNECTING", "CONFIG MISSING"}
        and not printer_status_upper.startswith("CONN ERROR")
        and not printer_status_upper.startswith("ERROR ")
    )
    temp_num_class = "temp-num active" if printer_is_active else "temp-num"
    cobot_ip = server_ip
    cobot_port = modbus_port
    raspberry_online = system_status_is_fresh
    cobot_online = raspberry_online and str(robot_status).strip().lower() == "connected"
    database_online = not df_sys.empty
    online_count = sum([raspberry_online, printer_connected, cobot_online, database_online])
    if online_count == 4:
        online_badge = "good"
        system_text = "System Active"
        status_dot_class = "online"
    elif online_count > 0:
        online_badge = "warn"
        system_text = "System Not Ready"
        status_dot_class = "warn"
    else:
        online_badge = "bad"
        system_text = "System Offline"
        status_dot_class = "offline"

    temp_history.append(temp if temp is not None else (temp_history[-1] if temp_history else 55.0))
    temp_history = temp_history[-15:]
    if temp is None:
        temp_color = "#5a5a54"
    elif temp > 70:
        temp_color = "#ba4335"
    elif temp > 65:
        temp_color = "#af650f"
    else:
        temp_color = "#1d7a4f"

    cpu_display = f"{cpu:.0f}%" if cpu is not None else "-"
    ram_display = f"{ram:.0f}%" if ram is not None else "-"
    disk_display = f"{disk:.0f}%" if disk is not None else "-"
    temp_display = f"{temp:.1f}°C" if temp is not None else "-"
    nozzle_display = f"{nozzle:.0f}°C" if nozzle is not None else "-"
    bed_display = f"{bed:.0f}°C" if bed is not None else "-"
    printer_task_display = printer_task if printer_task else "-"
    printer_remaining_display = printer_remaining if printer_remaining else "-"
    printer_stage_display = printer_stage if printer_stage else "-"
    printer_status_display = printer_status_upper if printer_status_upper else "-"
    printer_progress_display = f"{printer_progress:.0f}%" if printer_progress is not None else "-"

    total = len(df_parts_search_base)
    good = int((df_parts_search_base["_result_norm"] == "PASS").sum()) if total and "_result_norm" in df_parts_search_base.columns else 0
    ng = max(total - good, 0)
    yield_rate = (good / total * 100) if total else 0.0
    df_parts_search = df_parts_search_base

    if not df_parts.empty:
        current = df_parts.iloc[0]
        part_id = current.get("part_id", "—")
        side1 = normalize_status(current.get("side1", "N/A"))
        side2 = normalize_status(current.get("side2", "N/A"))
        side3 = normalize_status(current.get("side3", "N/A"))
        defect_s1 = str(current.get("defect_s1") or "-")
        defect_s2 = str(current.get("defect_s2") or "-")
        defect_s3 = str(current.get("defect_s3") or "-")
        result = current.get("_result_norm", normalize_status(current.get("result", "N/A")))
        record_ts = format_timestamp(current.get("record_timestamp", ""))
    else:
        part_id = "—"
        side1 = side2 = side3 = "N/A"
        defect_s1 = defect_s2 = defect_s3 = "-"
        result = "N/A"
        record_ts = "N/A"

    with theme_switch_slot.container():
        st.markdown('<div class="theme-floating-anchor"></div>', unsafe_allow_html=True)
        next_theme = "☾" if not is_dark_theme(theme_mode) else "☀"
        if st.button(next_theme, key="dashboard_theme_toggle", help="Toggle theme"):
            st.session_state["dashboard_theme_mode"] = next_theme
            if hasattr(st, "rerun"):
                st.rerun()
            else:
                st.experimental_rerun()

    with topbar_slot.container():
        st.markdown(
            f"""
            <div class="floating-topbar-shell">
                <div class="topbar" style="margin-top: 0 !important;">
                    <div class="topbar-title">
                        <div class="topbar-name"><span class="topbar-name-accent">PROJECT A1 :</span> DEVELOPMENT OF AN AUTOMATED QUALITY INSPECTION SYSTEM FOR 3D PRINTING PROCESSES</div>
                        <div class="topbar-info">
                            <div class="status-pill {online_badge}">
                                <span class="status-orb {status_dot_class}"></span>
                                {system_text}
                            </div>
                            <div class="topbar-meta">
                                <span id="js_live_date">{now.strftime("%d %b %Y")}</span> |
                                <span id="js_live_time">{now.strftime("%H:%M:%S")}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    components.html(
        f"""
        <script>
          (function() {{
            const intervalMs = {int(DASHBOARD_AUTO_REFRESH_SECONDS * 1000)};
            const key = "__projectA1DashAutoRefresh";
            if (window.parent && !window.parent[key]) {{
              window.parent[key] = window.setInterval(function() {{
                window.parent.location.reload();
              }}, intervalMs);
            }}
          }})();
        </script>
        """,
        height=0,
    )

    with clock_script_slot.container():
        components.html(
            """
            <script>
            (function () {
              const parentDoc = window.parent && window.parent.document ? window.parent.document : document;
              if (window.__dashClockInterval) {
                window.clearInterval(window.__dashClockInterval);
              }
              const monthFmt = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", year: "numeric" });
              const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
              function updateClock() {
                const dateEl = parentDoc.getElementById("js_live_date");
                const timeEl = parentDoc.getElementById("js_live_time");
                if (!dateEl || !timeEl) return;
                const now = new Date();
                dateEl.textContent = monthFmt.format(now);
                timeEl.textContent = timeFmt.format(now);
              }
              updateClock();
              window.__dashClockInterval = window.setInterval(updateClock, 1000);
            })();
            </script>
            """,
            height=0,
        )

    with pi_slot.container():
        st.markdown(
            f"""
            <div class="card">
                <div class="card-title">
                    <div class="card-title-left">
                        <span class="card-label">Raspberry Pi Health</span>
                    </div>
                </div>
                <div class="stat-grid">
                    <div class="stat-box">
                        <div class="stat-lbl">CPU Load</div>
                        <div class="stat-val">{cpu_display}</div>
                        <div class="stat-sub">Current usage</div>
                        <div class="bar-track"><div class="bar-fill {metric_tone(cpu or 0)}" style="width:{min(cpu or 0, 100):.0f}%"></div></div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-lbl">RAM Usage</div>
                        <div class="stat-val">{ram_display}</div>
                        <div class="stat-sub">Memory load</div>
                        <div class="bar-track"><div class="bar-fill {metric_tone(ram or 0)}" style="width:{min(ram or 0, 100):.0f}%"></div></div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-lbl">Disk Usage</div>
                        <div class="stat-val">{disk_display}</div>
                        <div class="stat-sub">Storage fill</div>
                        <div class="bar-track"><div class="bar-fill {metric_tone(disk or 0, warn=75, bad=90)}" style="width:{min(disk or 0, 100):.0f}%"></div></div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-lbl">CPU Temp</div>
                        <div class="stat-val" style="color:{temp_color};">{temp_display}</div>
                        <div class="stat-sub">Processor heat</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with pr_slot.container():
        st.markdown(
            f"""
            <div class="card card-bambu">
                <div class="card-title">
                    <div class="card-title-left">
                        <span class="card-label">Bambu A1 Status</span>
                    </div>
                </div>
                <div class="printer-task">
                    <div class="meta-label">Current Task</div>
                    <div class="printer-task-name">{printer_task_display}</div>
                </div>
                <div class="meta-grid section-gap">
                    <div class="meta-box">
                        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: start;">
                            <div>
                                <div class="meta-label">Time Remaining</div>
                                <div class="meta-value">{printer_remaining_display}</div>
                            </div>
                            <div>
                                <div class="meta-label">Current Stage</div>
                                <div class="meta-value">{printer_stage_display}</div>
                            </div>
                        </div>
                    </div>
                    <div class="meta-box">
                        <div class="meta-label">Printer Status</div>
                        <div class="meta-value">{printer_status_display}</div>
                    </div>
                </div>
                <div class="printer-grid section-gap">
                    <div class="temp-box">
                        <div class="{temp_num_class}">{nozzle_display}</div>
                        <div class="temp-lbl">Temp Nozzle</div>
                        <div class="mini-progress"><div class="mini-fill tone-warn" style="width:{min(max((nozzle or 0) / 3, 0), 100):.0f}%"></div></div>
                    </div>
                    <div class="temp-box cool">
                        <div class="{temp_num_class}">{bed_display}</div>
                        <div class="temp-lbl">Temp Bed</div>
                        <div class="mini-progress"><div class="mini-fill tone-blue" style="width:{min(max((bed or 0) / 1.2, 0), 100):.0f}%"></div></div>
                    </div>
                </div>
                <div class="progress-wrap section-gap">
                    <div class="progress-head">
                        <span class="progress-label">Progress</span>
                        <span class="progress-value">{printer_progress_display}</span>
                    </div>
                    <div class="progress-track"><div class="progress-fill" style="width:{min(max(printer_progress or 0, 0), 100):.0f}%"></div></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with extra_left_slot.container():
        st.markdown(
            f"""
            <div class="card card-empty">
                <div class="card-title" style="margin-bottom: 10px;">
                    <div class="card-title-left">
                        <span class="card-label">Project Info</span>
                    </div>
                </div>
                <div class="project-info">
                    <div class="info-columns">
                        <div class="info-panel compact">
                            <div class="info-grid">
                                <div class="info-row">
                                    <div class="info-label">Advisor</div>
                                    <div class="info-value">Asst. Prof. Noppadol Kumanuvong</div>
                                </div>
                                <div class="info-row">
                                    <div class="info-label">Build</div>
                                    <div class="info-value"><strong>2026.06.02</strong></div>
                                </div>
                            </div>
                        </div>
                        <div class="info-panel">
                            <div class="info-kicker">Team</div>
                            <div class="info-value creators">
                                <div>65070507601 KHWANKHAO KEAWDIAU</div>
                                <div>65070507626 JIRASAK SOMJIT</div>
                                <div>65070507647 TANANART WANGMOON</div>
                            </div>
                        </div>
                    </div>
                    <div class="project-logo-wrap">
                        <img class="project-logo" src="{logo_uri}" alt="TME Logo">
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with co_slot.container():
        st.markdown(
            f"""
            <div class="status-card">
                <div class="status-head">
                    <span class="status-title">Status</span>
                    <span class="card-note">Live connection state</span>
                </div>
                <div class="status-list">
                    <div class="status-row">
                        <div class="status-row-name">
                            <span class="status-orb {'online' if raspberry_online else 'offline'}"></span>
                            <span>Raspberry</span>
                        </div>
                        <span class="status-row-note">{'ONLINE' if raspberry_online else 'OFFLINE'}</span>
                    </div>
                    <div class="status-row">
                        <div class="status-row-name">
                            <span class="status-orb {'online' if printer_connected else 'offline'}"></span>
                            <span>Bambu Lab A1</span>
                        </div>
                        <span class="status-row-note">{'ONLINE' if printer_connected else 'OFFLINE'}</span>
                    </div>
                    <div class="status-row">
                        <div class="status-row-name">
                            <span class="status-orb {'online' if cobot_online else 'offline'}"></span>
                            <span>Cobot</span>
                        </div>
                        <span class="status-row-note">{'ONLINE' if cobot_online else 'OFFLINE'}</span>
                    </div>
                    <div class="status-row">
                        <div class="status-row-name">
                            <span class="status-orb {'online' if database_online else 'offline'}"></span>
                            <span>Database</span>
                        </div>
                        <span class="status-row-note">{'ONLINE' if database_online else 'OFFLINE'}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with inspection_slot.container():
        selected_row = df_parts.iloc[0] if not df_parts.empty else None
        search_mode_active = False

        st.markdown(
            f"""
            <div id="inspection-card-anchor"></div>
            <div class="card-title" style="margin-bottom: 8px;">
                <div class="card-title-left">
                    <span class="card-label">Inspection Overview</span>
                </div>
                <span class="card-note">Search / Live View</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div id="inspection-controls-anchor"></div>', unsafe_allow_html=True)

        mode_col, part_col, result_col, date_col, time_col = st.columns([0.78, 0.95, 0.9, 0.95, 1.35], gap="small")
        with mode_col:
            selected_mode = st.selectbox(
                "Mode",
                ["Live Update", "Search"],
                key="inspection_mode",
                label_visibility="collapsed",
            )
            search_mode_active = selected_mode == "Search"
        with part_col:
            part_query = st.text_input(
                "PART #",
                placeholder="PART # (e.g. 123)",
                key="inspection_part_query",
                label_visibility="collapsed",
                disabled=not search_mode_active,
            )

        part_term = str(part_query).strip().replace("#", "")
        search_active = search_mode_active or bool(part_term)

        search_pool = df_parts_search
        if part_term:
            search_pool = search_pool[search_pool["_part"].str.contains(part_term, case=False, na=False)]

        result_options = ["All results"]
        if search_active and not search_pool.empty:
            result_values = sorted([val for val in search_pool["_result_norm"].dropna().unique().tolist() if str(val).strip()])
            result_options.extend(result_values)

        with result_col:
            selected_result_text = st.selectbox(
                "Result",
                result_options,
                key="inspection_result",
                label_visibility="collapsed",
                disabled=not search_active,
            )

        if search_active and selected_result_text != "All results":
            search_pool = search_pool[search_pool["_result_norm"] == selected_result_text]

        unique_dates = []
        if search_active and not search_pool.empty:
            unique_dates = [date_text for date_text in search_pool["_date_text"].dropna().unique().tolist() if date_text]
        date_options = ["All dates"] + unique_dates

        with date_col:
            selected_date_text = st.selectbox(
                "Date",
                date_options,
                key="inspection_date",
                label_visibility="collapsed",
                disabled=not search_active,
            )

        if search_active and selected_date_text != "All dates":
            search_pool = search_pool[search_pool["_date_text"] == selected_date_text]

        match_map = {}
        match_labels = []
        if search_active and not search_pool.empty:
            match_labels = search_pool["_match_label"].tolist()
            match_map = dict(zip(match_labels, search_pool.index.tolist()))

        time_options = match_labels if match_labels else ["No match"]
        with time_col:
            selected_match_label = st.selectbox(
                "Time / Part",
                time_options,
                key="inspection_time_part",
                label_visibility="collapsed",
                disabled=not search_active or not match_labels,
            )

        if search_active:
            if search_pool.empty:
                selected_row = None
            else:
                selected_row = search_pool.loc[match_map[selected_match_label]]

        fields = record_to_inspection_fields(selected_row)
        view_part_id = fields["part_id"]
        view_side1 = fields["side1"]
        view_side2 = fields["side2"]
        view_side3 = fields["side3"]
        view_defect_s1 = fields["defect_s1"]
        view_defect_s2 = fields["defect_s2"]
        view_defect_s3 = fields["defect_s3"]
        view_capture_s1 = fields["capture_s1"]
        view_capture_s2 = fields["capture_s2"]
        view_capture_s3 = fields["capture_s3"]
        view_dim_top = fields["dim_top"]
        view_dim_bottom = fields["dim_bottom"]
        view_dim_length = fields["dim_length"]
        view_result = fields["result"]
        view_record_ts = fields["record_ts"]
        capture_gallery = render_capture_gallery_modals({
            1: view_capture_s1,
            2: view_capture_s2,
            3: view_capture_s3,
        })
        capture_side_1 = render_capture_cell(view_capture_s1, 1)
        capture_side_2 = render_capture_cell(view_capture_s2, 2)
        capture_side_3 = render_capture_cell(view_capture_s3, 3)

        side1_tone = side_status_tone(view_side1)
        side2_tone = side_status_tone(view_side2)
        side3_tone = side_status_tone(view_side3)
        side1_class = side1_tone if side1_tone in {"good", "ng"} else ""
        side2_class = side2_tone if side2_tone in {"good", "ng"} else ""
        side3_class = side3_tone if side3_tone in {"good", "ng"} else ""
        side1_badge = "badge-good" if side1_tone == "good" else "badge-ng" if side1_tone == "ng" else "badge-neutral"
        side2_badge = "badge-good" if side2_tone == "good" else "badge-ng" if side2_tone == "ng" else "badge-neutral"
        side3_badge = "badge-good" if side3_tone == "good" else "badge-ng" if side3_tone == "ng" else "badge-neutral"
        overall_class = "overall-pass" if view_result == "PASS" else "overall-fail" if view_result in {"FAIL", "NG"} else "overall-neutral"
        dim_top_class = dimension_alert_class(view_dim_top, "top")
        dim_bottom_class = dimension_alert_class(view_dim_bottom, "bottom")
        dim_length_class = dimension_alert_class(view_dim_length, "length")

        with gallery_slot.container():
            st.markdown(capture_gallery, unsafe_allow_html=True)

        st.markdown(
            f"""
            <div class="inspection-layout">
                <div class="capture-grid">
                    <div class="capture-cell">
                        {capture_side_1}
                    </div>
                    <div class="capture-cell">
                        {capture_side_2}
                    </div>
                    <div class="capture-cell">
                        {capture_side_3}
                    </div>
                </div>
                <div class="dim-block">
                    <div class="record-panel">
                        <div class="record-head">
                            <div class="record-part">PART #{view_part_id}</div>
                            <div class="record-ts">{view_record_ts}</div>
                        </div>
                        <div class="record-grid">
                            <div class="record-col">
                                <div class="record-col-title">DEFECT</div>
                                <div class="record-line"><span>DEFECT_S1</span><span class="record-val defect">{view_defect_s1}</span></div>
                                <div class="record-line"><span>DEFECT_S2</span><span class="record-val defect">{view_defect_s2}</span></div>
                                <div class="record-line"><span>DEFECT_S3</span><span class="record-val defect">{view_defect_s3}</span></div>
                            </div>
                            <div class="record-col">
                                <div class="record-col-title">DIMENSION</div>
                                <div class="record-line"><span>Top</span><span class="record-val {dim_top_class}">{view_dim_top}</span></div>
                                <div class="record-line"><span>Bottom</span><span class="record-val {dim_bottom_class}">{view_dim_bottom}</span></div>
                                <div class="record-line"><span>Length</span><span class="record-val {dim_length_class}">{view_dim_length}</span></div>
                                <div class="dimension-target-note">
                                    <div>Target Top: 19.50 +/- 0.30 mm</div>
                                    <div>Target Bottom: 24.50 +/- 0.30 mm</div>
                                    <div>Target Length: 90.00 +/- 0.30 mm</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="side-grid">
                    <div class="side-item {side1_class}">
                        <span class="side-name">SIDE 1</span>
                        <span class="side-badge {side1_badge}">{view_side1}</span>
                    </div>
                    <div class="side-item {side2_class}">
                        <span class="side-name">SIDE 2</span>
                        <span class="side-badge {side2_badge}">{view_side2}</span>
                    </div>
                    <div class="side-item {side3_class}">
                        <span class="side-name">SIDE 3</span>
                        <span class="side-badge {side3_badge}">{view_side3}</span>
                    </div>
                </div>
                <div class="overall-box {overall_class}">
                    <div class="overall-head">Result</div>
                    <div class="overall-value">{view_result}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with history_slot.container():
        st.markdown('<div id="recent-records-anchor"></div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="card-title" style="margin: 0 0 2px 0; padding: 0;">
                <div class="card-title-left">
                    <span class="card-label">Recent Records</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(render_history_table(df_parts), unsafe_allow_html=True)

    with quality_slot.container():
        st.markdown(
            f"""
            <div class="card">
                <div class="card-title">
                    <div class="card-title-left">
                        <span class="card-label">Quality Summary</span>
                    </div>
                    <span class="card-note">Last update {record_ts}</span>
                </div>
                <div class="q-grid">
                    <div class="q-box total"><div class="q-num">{total}</div><div class="q-sub">Total</div></div>
                    <div class="q-box pass"><div class="q-num green">{good}</div><div class="q-sub">Pass</div></div>
                    <div class="q-box fail"><div class="q-num red">{ng}</div><div class="q-sub">Fail</div></div>
                    <div class="q-box yield"><div class="q-num blue">{yield_rate:.1f}%</div><div class="q-sub">Yield</div></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with ng_chart_slot.container():
        side_rows = build_side_defect_counts(df_parts_search_base)
        st.markdown(
            """
            <div id="ng-chart-anchor"></div>
            <div class="chart-shell">
                <div class="chart-head chart-head-main">
                    <span class="chart-title chart-title-main">DEFECT BY SIDE</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            defect_by_side_chart(side_rows, theme_mode),
            use_container_width=True,
            config=CHART_CONFIG,
            key="defect_by_side_chart_main",
        )

    with trend_chart_slot.container():
        default_dimension = st.session_state.get("_dash_dimension_chart_key", "top")
        if default_dimension not in DIMENSION_CHART_FIELDS:
            default_dimension = "top"
        st.markdown('<div id="trend-chart-anchor"></div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="chart-shell">
                <div class="chart-head chart-head-main" style="margin-bottom:0;">
                    <span class="chart-title chart-title-main">DIMENSION CONTROL CHART</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="dimension-select-anchor"></div>', unsafe_allow_html=True)
        selected_dimension = st.selectbox(
            "Dimension chart selector",
            options=list(DIMENSION_CHART_FIELDS.keys()),
            index=list(DIMENSION_CHART_FIELDS.keys()).index(default_dimension),
            format_func=lambda key: DIMENSION_CHART_FIELDS[key]["label"],
            key="_dash_dimension_chart_key",
            label_visibility="collapsed",
        )
        chart_labels, chart_values = extract_dimension_chart_points(df_parts_search_base, selected_dimension, limit=12)
        st.plotly_chart(
            dimension_control_chart(tuple(chart_labels), tuple(chart_values), theme_mode, selected_dimension),
            use_container_width=True,
            config=CHART_CONFIG,
            key="dimension_control_chart_main",
        )

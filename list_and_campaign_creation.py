"""
Local copy of HeyReach pipeline helper (simplified for full-work-view).
This copy avoids exiting on missing config and keeps defaults so app can import safely.
"""

import os
import sys
import time
import json
import logging
import requests
import pandas as pd
from datetime import datetime
import toml

def parse_linkedin_accounts(accounts_raw: str) -> list[dict]:
    if not accounts_raw or not accounts_raw.strip():
        return []
    try:
        accounts = json.loads(accounts_raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Ошибка парсинга LINKEDIN_ACCOUNTS: {e}") from e
    parsed = []
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        if "id" not in acc:
            continue
        try:
            parsed.append({"id": int(acc["id"]), "name": str(acc.get("name", "")).strip()})
        except (ValueError, TypeError):
            continue
    return parsed

def load_linkedin_accounts() -> list[dict]:
    secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
    config_path = os.path.join(os.path.dirname(__file__), "config.toml")
    config_file = secrets_path if os.path.exists(secrets_path) else config_path
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = toml.load(f)
        return config.get("linkedin_accounts", [])
    except Exception as e:
        logging.warning(f"Ошибка загрузки TOML config: {e}")
        return []

# Do NOT call load_config at import time in this local copy. Provide safe defaults.
API_KEY = None
LINKEDIN_ACCOUNTS = []
ACCOUNT_IDS = []

BASE_URL  = "https://api.heyreach.io/api/public"
CSV_PATH  = "filtered_leads.csv"

_TS           = datetime.now().strftime("%Y-%m-%d %H:%M")
CAMPAIGN_NAME = f"Auto Campaign — {_TS}"
LIST_NAME     = f"Auto List — {_TS}"

MSG_1      = "Hi {FIRST_NAME}, I came across your profile and would love to connect!"
MSG_1_FB   = "Hi there, I came across your profile and would love to connect!"
MSG_2      = "Hi {FIRST_NAME}, thanks for connecting! Would love to explore how we might work together."
MSG_2_FB   = "Hi there, thanks for connecting! Would love to explore how we might work together."
MSG_3      = "Hi {FIRST_NAME}, just following up in case my last message got buried!"
MSG_3_FB   = "Hi there, just following up in case my last message got buried!"

SCHEDULE_TIMEZONE = "Europe/Amsterdam"
SCHEDULE_START    = "09:00:00"
SCHEDULE_END      = "18:00:00"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def _headers() -> dict:
    return {"X-API-KEY": API_KEY, "Content-Type": "application/json"}

def _post(path: str, body: dict, retries: int = 3) -> dict:
    url = f"{BASE_URL}{path}"
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, headers=_headers(), json=body, timeout=30, allow_redirects=False)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 15))
                time.sleep(wait)
                continue
            if not r.ok:
                r.raise_for_status()
            return r.json() if r.content else {}
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise

def _get(path: str, params: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    if not r.ok:
        r.raise_for_status()
    return r.json() if r.content else {}

def run_pipeline_custom(*args, **kwargs):
    raise RuntimeError("This function is a placeholder in the local copy. Place your HeyReach config in the original repo to enable pipeline.")

if __name__ == "__main__":
    print("Local list_and_campaign_creation placeholder. No action when run as script.")

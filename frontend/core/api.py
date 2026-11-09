"""Client for the FastAPI backend (used when AIOPS_MODE=api).

The backend team implements these endpoints; response shapes are documented in docs/API_CONTRACT.md.
Everything the dashboard needs from the backend goes through this file, so a contract change is a one-file change.
"""
from __future__ import annotations

import pandas as pd
import requests

from . import config


class ApiError(Exception):
    pass


def _h() -> dict:
    t = config.settings().get("api_token", "")
    return {"Authorization": f"Bearer {t}"} if t else {}


def _call(method: str, path: str, **kw):
    url = config.settings()["api_url"] + path
    try:
        r = requests.request(method, url, headers=_h(), timeout=15, **kw)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise ApiError(f"{method} {path} failed: {e.__class__.__name__}") from e


def login(username: str, password: str) -> str:
    return _call("POST", "/auth/login", json={"username": username, "password": password})["access_token"]


def ranking() -> pd.DataFrame:
    items = _call("GET", "/risk/ranking")["items"]
    return pd.DataFrame(items)


def incidents() -> list[dict]:
    return _call("GET", "/incidents")["items"]


def work_orders() -> list[dict]:
    return _call("GET", "/work-orders")["items"]


def decide(wo_id: str, decision: str, reason: str = "") -> dict:
    return _call("POST", f"/work-orders/{wo_id}/{decision}", json={"reason": reason})


def chat(session_id: str, question: str) -> dict:
    return _call("POST", "/chat", json={"session_id": session_id, "question": question})


def audit() -> list[dict]:
    return _call("GET", "/audit-logs")["items"]

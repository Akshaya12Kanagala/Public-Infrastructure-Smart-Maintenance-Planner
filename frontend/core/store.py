"""SQLite persistence for incidents, work-orders, audit trail, scenario injections and small settings.
Everything here is written by the app from REAL events (detections, decisions, injections)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT, opened_at TEXT, closed_at TEXT, status TEXT,
  severity REAL, urgency REAL, level TEXT, signals TEXT, runbook_id TEXT, match_score REAL,
  proactive INTEGER, err_at_detection REAL, hint TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS work_orders (
  id TEXT PRIMARY KEY, incident_id INTEGER, created_at TEXT, status TEXT, assignee TEXT,
  payload TEXT, decided_by TEXT, decided_at TEXT, decision_reason TEXT,
  executed_at TEXT, execution TEXT, verified_at TEXT, verification TEXT);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS injections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scenario TEXT, flag TEXT, variant TEXT, previous TEXT, mode TEXT,
  started_at TEXT, ended_at TEXT, detected_at TEXT, resolved_at TEXT, incident_id INTEGER, note TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(s: str | None):
    return datetime.fromisoformat(s) if s else None


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(config.data_dir() / "app.db", timeout=15)
        c.row_factory = sqlite3.Row
        try:
            c.executescript(SCHEMA)
            yield c
            c.commit()
        finally:
            c.close()


def q(sql: str, args: tuple = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def x(sql: str, args: tuple = ()) -> int:
    with conn() as c:
        return c.execute(sql, args).lastrowid or 0


# ---- key/value
def kv_get(key: str, default=None):
    r = q("SELECT v FROM kv WHERE k=?", (key,))
    return json.loads(r[0]["v"]) if r else default


def kv_set(key: str, value) -> None:
    x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, json.dumps(value)))


# ---- audit
def audit(actor: str, action: str, target: str = "", detail: dict | None = None) -> None:
    x("INSERT INTO audit(ts,actor,action,target,detail) VALUES(?,?,?,?,?)",
      (now(), actor, action, target, json.dumps(detail or {}, default=str)))


def audit_rows(limit: int = 500) -> list[dict]:
    return q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))


def audit_count(action: str, target: str, since_iso: str) -> int:
    r = q("SELECT COUNT(*) n FROM audit WHERE action=? AND target=? AND ts>=?", (action, target, since_iso))
    return r[0]["n"]

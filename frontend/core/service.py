"""Facade used by every page. local mode = analytics on real Prometheus data; api mode = FastAPI backend.
This is the only module (besides ui.py) that imports Streamlit."""
from __future__ import annotations

import json
import time

import pandas as pd
import streamlit as st

from . import api, config, engine, executor, prom as promlib, rulebook, store, workorders


def mode() -> str:
    return config.settings().get("mode", "local")


# ----------------------------------------------------------------------------- snapshot
@st.cache_data(ttl=20, show_spinner=False)
def _snapshot_cached(_bucket: int) -> engine.Snapshot:
    snap = engine.evaluate()
    # automation: only acts if the executor is enabled and the runbook allows it without approval
    if snap.ok and store.kv_get("automation_mode", config.settings()["automation"]["default_mode"]) == "auto_within_limits":
        for wo_id in snap.new_work_orders:
            wo = get_work_order(wo_id)
            if wo and wo["payload"]["estimate"]["approval"].lower().startswith("not required"):
                decide(wo_id, "approve", "Automatic: runbook allows it within limits", actor="automation", execute=True)
    return snap


_DEFAULTS = {"kind": "app", "zone": "", "status": "healthy", "severity": 0.0, "urgency": 0.0, "cost_norm": 0.1,
             "impact": 0.1, "cost_per_min": 0.0, "exposure_per_min": 0.0, "rps": None, "err_ratio": None,
             "p95_ms": None, "cpu": None, "mem_mib": None, "failed_per_min": None, "z_max": None, "eta_min": None,
             "signals": [], "components": {}, "symptom": "", "anomalous": False, "has_data": True, "hint": ""}


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Make a backend ranking usable by every page even if optional fields are missing (see API_CONTRACT.md)."""
    if df.empty or "service" not in df.columns:
        return pd.DataFrame(columns=["service", *_DEFAULTS])
    for col, default in _DEFAULTS.items():
        if col not in df.columns:
            df[col] = [default.copy() if isinstance(default, (list, dict)) else default for _ in range(len(df))]
    return df.sort_values("urgency", ascending=False).reset_index(drop=True)


def snapshot() -> engine.Snapshot:
    if mode() == "api":
        try:
            df = _normalize(api.ranking())
            return engine.Snapshot(True, "ok", pd.Timestamp.utcnow().to_pydatetime(), table=df, meta={"api": True})
        except api.ApiError as e:
            return engine.Snapshot(False, str(e), pd.Timestamp.utcnow().to_pydatetime())
    return _snapshot_cached(int(time.time() // 20))


# ----------------------------------------------------------------------------- incidents & work orders
def incidents(status: str | None = None) -> list[dict]:
    if mode() == "api":
        return api.incidents()
    sql = "SELECT * FROM incidents" + (" WHERE status=?" if status else "") + " ORDER BY id DESC"
    return store.q(sql, (status,) if status else ())


def work_orders() -> list[dict]:
    if mode() == "api":
        return api.work_orders()
    rows = store.q("SELECT * FROM work_orders ORDER BY created_at DESC")
    return [_wo(r) for r in rows]


def _wo(r: dict) -> dict:
    r = dict(r)
    for k in ("payload", "execution", "verification"):
        r[k] = json.loads(r[k]) if r.get(k) else None
    return r


def get_work_order(wo_id: str) -> dict | None:
    rows = store.q("SELECT * FROM work_orders WHERE id=?", (wo_id,))
    return _wo(rows[0]) if rows else None


def decide(wo_id: str, decision: str, reason: str, actor: str, execute: bool = False) -> dict:
    """decision: approve | reject. Executes the planned action only if asked, allowed and enabled."""
    if mode() == "api":
        return api.decide(wo_id, decision, reason)
    wo = get_work_order(wo_id)
    if not wo or wo["status"] not in ("proposed", "approved"):
        return {"ok": False, "output": "Work-order is not open for a decision"}
    ts = store.now()
    if decision == "reject":
        store.x("UPDATE work_orders SET status='rejected', decided_by=?, decided_at=?, decision_reason=? WHERE id=?",
                (actor, ts, reason, wo_id))
        store.audit(actor, "work_order_rejected", wo_id, {"reason": reason})
        return {"ok": True, "output": "Rejected"}
    store.x("UPDATE work_orders SET status='approved', decided_by=?, decided_at=?, decision_reason=? WHERE id=?",
            (actor, ts, reason, wo_id))
    store.audit(actor, "work_order_approved", wo_id, {"reason": reason, "execute": execute})
    out = {"ok": True, "output": "Approved"}
    if execute:
        res = executor.execute(wo["payload"]["plan"], actor)
        out = res
        if res["ok"]:
            store.x("UPDATE work_orders SET status='executed', executed_at=?, execution=? WHERE id=?",
                    (store.now(), json.dumps(res), wo_id))
        else:
            store.x("UPDATE work_orders SET execution=? WHERE id=?", (json.dumps(res), wo_id))
    return out


def assign(wo_id: str, assignee: str, actor: str) -> None:
    store.x("UPDATE work_orders SET assignee=? WHERE id=?", (assignee, wo_id))
    store.audit(actor, "work_order_assigned", wo_id, {"assignee": assignee})


def mark_done_manually(wo_id: str, actor: str) -> None:
    store.x("UPDATE work_orders SET status='executed', executed_at=?, execution=? WHERE id=?",
            (store.now(), json.dumps({"ok": True, "output": "Executed manually by a person", "manual": True}), wo_id))
    store.audit(actor, "work_order_manual_execution", wo_id, {})


def verify(wo_id: str, actor: str) -> dict:
    """Compare the service now with its state at detection, at least 3 minutes after execution."""
    wo = get_work_order(wo_id)
    if not wo or not wo.get("executed_at"):
        return {"state": "not_executed"}
    waited = (store.parse_ts(store.now()) - store.parse_ts(wo["executed_at"])).total_seconds() / 60
    if waited < 3:
        return {"state": "waiting", "minutes_left": round(3 - waited, 1)}
    snap = snapshot()
    svc = wo["payload"]["service"]
    row = snap.table[snap.table["service"] == svc]
    if row.empty:
        return {"state": "unknown"}
    now_sev, before = float(row.iloc[0]["severity"]), float(wo["payload"]["snapshot"]["severity"] or 0)
    th = config.settings()["thresholds"]
    improved = now_sev < th["close_severity"] or (before > 0 and now_sev <= 0.5 * before and now_sev < 0.3)
    res = {"state": "verified" if improved else "not_improved", "severity_before": before, "severity_now": now_sev,
           "checked_at": store.now()}
    store.x("UPDATE work_orders SET status=?, verified_at=?, verification=? WHERE id=?",
            ("verified" if improved else "needs_attention", store.now(), json.dumps(res), wo_id))
    store.audit(actor, "verification", wo_id, res)
    return res


def rollback(wo_id: str, actor: str) -> dict:
    wo = get_work_order(wo_id)
    if not wo or not wo.get("execution"):
        return {"ok": False, "output": "Nothing executed"}
    res = executor.rollback(wo["payload"]["plan"], wo["execution"].get("previous"), actor)
    if res["ok"]:
        store.x("UPDATE work_orders SET status='rolled_back' WHERE id=?", (wo_id,))
    return res


# ----------------------------------------------------------------------------- assistant
def answer(question: str, session_id: str) -> dict:
    """Return {'answer': str, 'citations': [..]}. api mode asks the backend (LLM + RAG);
    local mode answers from the rulebook and the live ranking only, and says so."""
    if mode() == "api":
        return api.chat(session_id, question)
    ql = question.lower()
    snap = snapshot()
    parts, cites = [], []
    if snap.ok and any(w in ql for w in ("risk", "rank", "priorit", "at risk", "saturat", "worst", "first")):
        top = snap.table[snap.table["urgency"] > 0].head(5)
        if top.empty:
            parts.append("No service is currently above the healthy range.")
        else:
            parts.append("Highest urgency right now:\n" + "\n".join(
                f"- **{r.service}** ({r.status}): urgency {r.urgency:.1f}; " + ("; ".join(r.signals[:2]) or "trend")
                for r in top.itertuples()))
            cites.append({"type": "metric", "title": "Live ranking from Prometheus metrics"})
    hits = rulebook.search_chunks(question, 3)
    if hits:
        parts.append("From the rulebook:")
        for h in hits:
            parts.append(f"**{h['id']}: {h['title']}**, {h['section'].title()}\n{h['text'][:700]}")
            cites.append({"type": "runbook", "title": f"{h['id']} / {h['section']}", "score": round(h['score'], 2)})
    if not parts:
        return {"answer": "No source, no answer: I found no runbook or live metric that matches this question. "
                          "Try describing the symptom (for example 'cart error rate is high').", "citations": []}
    return {"answer": "\n\n".join(parts), "citations": cites}


@st.cache_data(ttl=30, show_spinner=False)
def _series_cached(_bucket: int) -> dict:
    cfg = config.settings()
    p = promlib.Prom(cfg["prometheus_url"])
    try:
        return engine.fetch_series(p, promlib.discover(p), cfg)
    except promlib.PromError:
        return {}


def get_series() -> dict:
    """Time series for charts (always straight from Prometheus, in both modes)."""
    snap = snapshot()
    return snap.series or _series_cached(int(time.time() // 30))

"""Success metrics computed from REAL recorded events (incidents, decisions, scenario runs)."""
from __future__ import annotations

import statistics as st

from . import store


def _mins(a, b):
    if not a or not b:
        return None
    return (store.parse_ts(b) - store.parse_ts(a)).total_seconds() / 60


def _med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def repair_stats() -> dict:
    rows = store.q("""SELECT w.id, w.status, w.created_at, w.decided_at, w.executed_at, w.verified_at,
                             i.proactive, i.opened_at, i.closed_at, i.service, i.level
                      FROM work_orders w JOIN incidents i ON i.id = w.incident_id""")
    repaired = [r for r in rows if r["executed_at"]]
    out = {
        "work_orders": len(rows),
        "repaired": len(repaired),
        "proactive": sum(1 for r in repaired if r["proactive"]),
        "rejected": sum(1 for r in rows if r["status"] == "rejected"),
        "verified": sum(1 for r in rows if r["status"] == "verified"),
        "t_detect_to_decision": _med([_mins(r["created_at"], r["decided_at"]) for r in rows if r["decided_at"]]),
        "t_decision_to_action": _med([_mins(r["decided_at"], r["executed_at"]) for r in repaired]),
        "t_detect_to_repair": _med([_mins(r["opened_at"], r["executed_at"]) for r in repaired]),
        "rows": rows,
    }
    out["proactive_pct"] = (out["proactive"] / out["repaired"]) if out["repaired"] else None
    return out


def scenario_stats() -> dict:
    rows = store.q("SELECT * FROM injections ORDER BY id DESC")
    by_mode: dict[str, list[float]] = {"manual": [], "assisted": []}
    detect: list[float] = []
    for r in rows:
        ttr = _mins(r["started_at"], r["resolved_at"])
        if ttr is not None and r["mode"] in by_mode:
            by_mode[r["mode"]].append(ttr)
        d = _mins(r["started_at"], r["detected_at"])
        if d is not None and r["mode"] == "assisted":
            detect.append(d)
    return {"rows": rows, "ttr_manual": by_mode["manual"], "ttr_assisted": by_mode["assisted"],
            "detect_delay": detect, "median_manual": _med(by_mode["manual"]),
            "median_assisted": _med(by_mode["assisted"])}

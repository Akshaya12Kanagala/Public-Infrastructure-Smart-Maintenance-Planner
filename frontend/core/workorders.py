"""Work-order generation from a detected incident + the matched runbook (template based, no invented numbers).
Effort, resources, approval and steps come from the rulebook; evidence comes from live metrics."""
from __future__ import annotations

import json
from datetime import timedelta

from . import config, executor, store

PRIORITY = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"}


def create(incident_id: int, row: dict, entry, score: float, trusted: bool, opened_at: str) -> str:
    cfg = config.settings()
    level = row["status"]
    sla_min = cfg["sla_response_minutes"].get(level, 1440)
    plan = executor.plan_action(entry, row["service"])
    due = store.parse_ts(opened_at) + timedelta(minutes=sla_min)
    payload = {
        "title": f"[{PRIORITY.get(level, 'P4')}] {row['service']}: {entry.title}",
        "service": row["service"],
        "priority": PRIORITY.get(level, "P4"),
        "level": level,
        "summary": f"{row['service']} is {level} (severity {row['severity']:.2f}, urgency {row['urgency']:.1f}). "
                   + ("; ".join(row["signals"]) if row["signals"] else "Trend indicates an upcoming breach."),
        "evidence": row["signals"],
        "hint": row.get("hint", ""),
        "runbook": {"id": entry.id, "title": entry.title, "match_score": round(score, 3), "trusted": trusted},
        "steps": entry.steps(),
        "safety_limits": entry.bullets("safety limits"),
        "verify": entry.bullets("verify"),
        "rollback": entry.bullets("rollback"),
        "escalate_if": entry.bullets("escalate if"),
        "mishap": entry.bullets("common mishap and fix"),
        "estimate": {"effort_min": entry.effort_min, "resources": entry.meta.get("resources", "On-call engineer"),
                     "approval": entry.meta.get("approval", "required"), "risk": entry.meta.get("severity", "Medium")},
        "plan": plan,
        "sla_minutes": sla_min,
        "sla_due": due.isoformat(),
        "snapshot": {k: row.get(k) for k in ("severity", "urgency", "err_ratio", "p95_ms", "rps", "cpu", "mem_mib")},
    }
    wo_id = f"WO-{store.parse_ts(opened_at):%Y%m%d}-{incident_id:03d}"
    store.x("INSERT OR IGNORE INTO work_orders(id,incident_id,created_at,status,payload) VALUES(?,?,?,?,?)",
            (wo_id, incident_id, opened_at, "proposed", json.dumps(payload, default=str)))
    store.audit("system", "work_order_proposed", wo_id, {"service": row["service"], "runbook": entry.id})
    return wo_id


def to_markdown(wo: dict) -> str:
    p = wo["payload"]
    est = p["estimate"]
    lines = [f"# {wo['id']}: {p['title']}", "",
             f"**Status:** {wo['status']}  |  **Priority:** {p['priority']}  |  **SLA due:** {p['sla_due']}", "",
             "## Summary", p["summary"], ""]
    if p.get("hint"):
        lines += [f"**Likely cause:** {p['hint']}", ""]
    lines += ["## Estimated repair requirements",
              f"- Effort: about {est['effort_min']} minutes", f"- Resources: {est['resources']}",
              f"- Approval: {est['approval']}", f"- Risk level: {est['risk']}", "",
              f"## Runbook {p['runbook']['id']}: {p['runbook']['title']}"]
    lines += [f"{i}. {s}" for i, s in enumerate(p["steps"], 1)]
    lines += ["", "## Planned action", f"- {p['plan']['reason']}", f"- Command: `{p['plan']['command']}`", "",
              "## Verify"] + [f"- {v}" for v in p["verify"]]
    lines += ["", "## Rollback"] + [f"- {v}" for v in p["rollback"]]
    lines += ["", "## Escalate if"] + [f"- {v}" for v in p["escalate_if"]]
    return "\n".join(lines)

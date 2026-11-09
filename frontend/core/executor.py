"""Sandbox remediation: strictly allow-listed actions (docker compose restart, feature-flag rollback).

Safety: disabled unless executor.enabled=true; named targets only (validated against the registry or the
flag file); argument-list subprocess (no shell); dry-run preview; rate limit; kill switch; full audit trail.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, store

ALLOWED = {"restart", "flag_off", "none"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


# ----------------------------------------------------------------------------- flag file
def flagd_path() -> Path | None:
    p = config.settings().get("lab", {}).get("flagd_file", "")
    return Path(p) if p and Path(p).is_file() else None


def read_flags() -> dict | None:
    p = flagd_path()
    if not p:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("flags", {})
    except (OSError, ValueError):
        return None


def set_flag(flag: str, variant: str) -> tuple[bool, str, str | None]:
    """Set a flag's default variant in place (keeps the file's inode so the bind mount keeps working)."""
    p = flagd_path()
    if not p:
        return False, "Flag file not found (set AIOPS_DEMO_DIR or lab.flagd_file)", None
    if not SAFE_NAME.match(flag):
        return False, "Invalid flag name", None
    doc = json.loads(p.read_text(encoding="utf-8"))
    flags = doc.get("flags", {})
    if flag not in flags:
        return False, f"Flag '{flag}' does not exist in this demo version", None
    if variant not in flags[flag].get("variants", {}):
        return False, f"Variant '{variant}' does not exist for '{flag}'", None
    prev = flags[flag].get("defaultVariant")
    flags[flag]["defaultVariant"] = variant
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    return True, "ok", prev


def active_flags_for(service: str) -> list[dict]:
    """Flags currently not 'off' that belong to scenarios touching this service ('what changed recently')."""
    flags = read_flags() or {}
    out = []
    for sc in config.scenarios():
        if service in sc.get("services", []) and sc["flag"] in flags:
            cur = flags[sc["flag"]].get("defaultVariant")
            if cur and cur != "off":
                out.append({"flag": sc["flag"], "variant": cur, "scenario": sc["id"]})
    return out


# ----------------------------------------------------------------------------- planning
def plan_action(entry, service: str) -> dict:
    """Decide the concrete action for a runbook entry and a service. Returns a plan dict (not executed)."""
    def restart_plan(why: str):
        return {"type": "restart", "target": service, "reason": why}

    kind = entry.action
    plan = {"type": "none", "target": service, "reason": "Manual steps only (see runbook)"}
    if kind == "flag_off":
        cands = active_flags_for(service)
        if cands:
            c = cands[0]
            plan = {"type": "flag_off", "target": c["flag"], "variant_now": c["variant"], "service": service,
                    "reason": f"Feature flag '{c['flag']}' is on ({c['variant']}) and affects {service}: roll it back"}
        elif entry.fallback == "restart":
            plan = restart_plan("No recent change found; fallback to restarting the service")
        else:
            plan["reason"] = "No recent change found to roll back; investigate manually"
    elif kind == "restart":
        plan = restart_plan("Restart as relief (runbook)")
    plan["command"] = command_preview(plan)
    return plan


def command_preview(plan: dict) -> str:
    t, tgt = plan.get("type"), plan.get("target", "")
    if t == "restart":
        return f"docker compose restart {tgt}"
    if t == "flag_off":
        return f"set feature flag '{tgt}' -> off   (same as switching it off in the Feature Flag UI)"
    return "(no automatic command)"


# ----------------------------------------------------------------------------- execution
def can_execute(plan: dict | None = None) -> tuple[bool, str]:
    cfg = config.settings()["executor"]
    if store.kv_get("kill_switch", False):
        return False, "Kill switch is ON: all automation is stopped"
    if store.kv_get("automation_mode", config.settings()["automation"]["default_mode"]) == "suggest_only":
        return False, "Automation mode is 'suggest only'"
    if not cfg.get("enabled"):
        return False, "Executor is disabled (executor.enabled=false). Run the command manually."
    if not cfg.get("demo_dir") or not Path(cfg["demo_dir"]).is_dir():
        return False, "AIOPS_DEMO_DIR is not set or not found on this machine"
    if plan is not None:
        if plan.get("type") not in ALLOWED or plan.get("type") == "none":
            return False, "This runbook has no executable action"
        tgt = plan.get("target", "")
        if not SAFE_NAME.match(tgt):
            return False, "Target name rejected by the safety check"
        if plan["type"] == "restart" and tgt not in config.services():
            return False, f"'{tgt}' is not in the service registry"
        if plan["type"] == "flag_off" and tgt not in (read_flags() or {}):
            return False, f"Flag '{tgt}' not found in the flag file"
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()
        limit = cfg.get("max_actions_per_service_per_hour", 3)
        if store.audit_count("execute", tgt, since) >= limit:
            return False, f"Rate limit reached ({limit} actions per hour for '{tgt}'): escalate to a human"
    return True, "ok"


def execute(plan: dict, actor: str) -> dict:
    ok, why = can_execute(plan)
    if not ok:
        store.audit(actor, "execute_blocked", plan.get("target", ""), {"plan": plan, "reason": why})
        return {"ok": False, "output": why, "command": plan.get("command", "")}
    cfg = config.settings()["executor"]
    res = {"ok": False, "output": "", "command": command_preview(plan), "previous": None}
    if plan["type"] == "restart":
        try:
            cmd = ["docker", "compose"]
            if cfg.get("compose_file"):
                cmd += ["-f", cfg["compose_file"]]
            r = subprocess.run(cmd + ["restart", plan["target"]], cwd=cfg["demo_dir"],
                               capture_output=True, text=True, timeout=cfg.get("command_timeout_seconds", 120))
            res.update(ok=r.returncode == 0, output=(r.stdout + r.stderr).strip()[-1500:])
        except (OSError, subprocess.TimeoutExpired) as e:
            res["output"] = f"{e.__class__.__name__}: {e}"
    elif plan["type"] == "flag_off":
        done, msg, prev = set_flag(plan["target"], "off")
        res.update(ok=done, output=msg, previous=prev)
        if done:
            _link_injection_resolved(plan["target"])
    store.audit(actor, "execute", plan["target"], {"plan": plan, "result": res})
    return res


def rollback(plan: dict, previous: str | None, actor: str) -> dict:
    if plan.get("type") != "flag_off" or not previous:
        return {"ok": False, "output": "Nothing to roll back (restarts cannot be undone)"}
    if store.kv_get("kill_switch", False):
        return {"ok": False, "output": "Kill switch is ON"}
    done, msg, _ = set_flag(plan["target"], previous)
    store.audit(actor, "rollback", plan["target"], {"restored": previous, "ok": done, "msg": msg})
    return {"ok": done, "output": msg}


def _link_injection_resolved(flag: str) -> None:
    for r in store.q("SELECT id FROM injections WHERE flag=? AND resolved_at IS NULL", (flag,)):
        store.x("UPDATE injections SET resolved_at=?, ended_at=COALESCE(ended_at, ?) WHERE id=?",
                (store.now(), store.now(), r["id"]))

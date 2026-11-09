"""Preview analytics engine: turns REAL Prometheus metrics into anomaly flags, severity, urgency, incidents.

It exists so the dashboard works before the FastAPI/Scikit-learn services do. Once the backend is running
(AIOPS_MODE=api) the same tables come from the API instead. No data is generated here: if Prometheus
has no data, the UI shows an empty state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config, prom as promlib, rulebook, store, workorders

LEVELS = ["critical", "high", "medium", "low", "healthy"]
FLOOR = {"rps": 0.5, "err": 0.005, "p95": 5.0, "cpu": 0.02, "mem": 5.0}


@dataclass
class Snapshot:
    ok: bool
    message: str
    ts: datetime
    table: pd.DataFrame = field(default_factory=pd.DataFrame)
    series: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    new_work_orders: list = field(default_factory=list)


# ----------------------------------------------------------------------------- fetching
def _queries(disc: dict, cfg: dict) -> dict:
    svc, cont, kind = cfg["service_label"], cfg["container_label"], disc.get("kind_filter", "")

    def sel(extra: str = "") -> str:
        parts = [p for p in (kind, extra) if p]
        return "{" + ",".join(parts) + "}"

    qs = {}
    if disc.get("calls"):
        qs["rps"] = f"sum by ({svc}) (rate({disc['calls']}{sel()}[5m]))"
        err_sel = sel('status_code=~".*ERROR.*"')
        qs["err_rps"] = f"sum by ({svc}) (rate({disc['calls']}{err_sel}[5m]))"
    if disc.get("bucket"):
        qs["p95"] = f"histogram_quantile(0.95, sum by (le, {svc}) (rate({disc['bucket']}{sel()}[5m])))"
    if disc.get("cpu"):
        qs["cpu"] = f"max by ({cont}) ({disc['cpu']})"
    if disc.get("mem"):
        qs["mem"] = f"max by ({cont}) ({disc['mem']})"
    return qs


def fetch_series(p: promlib.Prom, disc: dict, cfg: dict) -> dict:
    step, minutes = cfg["step_seconds"], cfg["history_minutes"]
    qs = _queries(disc, cfg)
    svc, cont = cfg["service_label"], cfg["container_label"]
    raw = {}
    end_ts = (time.time() // step) * step  # one shared time grid for every query of this refresh
    for name, q in qs.items():
        raw[name] = p.range_by(q, cont if name in ("cpu", "mem") else svc, minutes, step, end_ts)
    out = {}
    rps = raw.get("rps", pd.DataFrame())
    if not rps.empty:
        out["rps"] = rps * 60.0  # requests per minute
        err = raw.get("err_rps", pd.DataFrame()).reindex_like(rps).fillna(0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = (err * 60.0) / out["rps"].where(out["rps"] > 0.05)
        out["err"] = ratio.clip(0, 1).fillna(0.0)
    if not raw.get("p95", pd.DataFrame()).empty:
        out["p95"] = raw["p95"] * (1000.0 if disc.get("latency_unit") == "s" else 1.0)
    reverse = {config.container_of(s): s for s in config.services()}
    for m in ("cpu", "mem"):
        df = raw.get(m, pd.DataFrame())
        if df.empty:
            continue
        df = df.rename(columns=reverse)
        df = df[[c for c in df.columns if c in config.services()]]
        if m == "cpu" and df.max().max() > 1.5:
            df = df / 100.0
        if m == "mem" and df.max().max() > 1e6:
            df = df / 1048576.0
        out[m] = df
    return out


# ----------------------------------------------------------------------------- analysis
def _robust(base: np.ndarray, cur: float, floor: float) -> tuple[float, float, float]:
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med)))
    scale = max(1.4826 * mad, 0.05 * abs(med), floor)
    return med, scale, (cur - med) / scale


def _eta(v: pd.Series, threshold: float, step_min: float, n: int = 12) -> float | None:
    """Minutes until a rising series crosses `threshold` (linear trend, only if the trend is convincing)."""
    y = v.iloc[-n:].values.astype(float)
    if len(y) < n or y[-1] >= threshold:
        return None
    x = np.arange(len(y)) * step_min
    slope, icpt = np.polyfit(x, y, 1)
    if slope <= 1e-9:
        return None
    pred = slope * x + icpt
    ss_res, ss_tot = float(((y - pred) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    if r2 < 0.6:
        return None
    eta = (threshold - y[-1]) / slope
    return float(eta) if 0 < eta <= 240 else None


def analyze_service(name: str, series: dict, cfg: dict) -> dict:
    th = cfg["thresholds"]
    zthr, slo = th["modified_z"], th["error_ratio_slo"]
    step = cfg["step_seconds"]
    win = max(2, round(cfg["window_minutes"] * 60 / step))
    base_n = round(cfg["baseline_minutes"] * 60 / step)
    cur, base, zs, comp, sig = {}, {}, {}, {}, []
    for m in ("rps", "err", "p95", "cpu", "mem"):
        df = series.get(m)
        if df is None or name not in df.columns:
            continue
        v = df[name].dropna()
        if len(v) < win + 8:
            continue
        window, hist = v.iloc[-win:], v.iloc[-(win + base_n):-win]
        cur[m] = float(window.mean())
        med, scale, z = _robust(hist.values, cur[m], FLOOR[m])
        base[m], zs[m] = med, z
    res = {"service": name, "has_data": bool(cur), "cur": cur, "base": base, "z": zs}
    if not cur:
        return {**res, "severity": 0.0, "components": {}, "signals": [], "eta": None, "anomalous": False}

    if "err" in cur and (zs["err"] > zthr or cur["err"] > slo):
        comp["errors"] = float(np.clip(cur["err"] / 0.25, 0, 1))
        sig.append(f"error ratio {cur['err']*100:.1f}% (normal {base['err']*100:.2f}%, SLO {slo*100:.0f}%)")
    if "p95" in cur and zs["p95"] > zthr:
        ratio = cur["p95"] / max(base["p95"], 1e-6)
        comp["latency"] = float(np.clip((ratio - 1.5) / 4.5, 0, 1))
        if comp["latency"] > 0:
            sig.append(f"p95 latency {cur['p95']:.0f} ms, {ratio:.1f}x normal ({base['p95']:.0f} ms)")
    if "rps" in cur:
        ratio = cur["rps"] / max(base["rps"], 1e-6)
        if zs["rps"] > zthr and ratio > 2 and base["rps"] > 0.5:
            comp["traffic_spike"] = float(np.clip((ratio - 2) / 6, 0, 1))
            sig.append(f"request rate {cur['rps']:.0f}/min, {ratio:.1f}x normal ({base['rps']:.0f}/min)")
        elif ratio < 0.3 and base["rps"] > 1:
            comp["traffic_drop"] = float(np.clip(0.8 * (1 - ratio / 0.3), 0, 1))
            sig.append(f"traffic dropped to {ratio*100:.0f}% of normal ({cur['rps']:.0f} vs {base['rps']:.0f}/min)")
    if "cpu" in cur and zs["cpu"] > zthr:
        comp["cpu"] = float(np.clip((cur["cpu"] - base["cpu"]) / 0.5, 0, 1))
        if comp["cpu"] > 0:
            sig.append(f"CPU {cur['cpu']*100:.0f}% (normal {base['cpu']*100:.0f}%)")
    if "mem" in series and name in series["mem"].columns:
        tail = series["mem"][name].dropna().iloc[-30:]
        if len(tail) >= 20 and tail.iloc[0] > 0:
            growth = float((tail.iloc[-1] - tail.iloc[0]) / tail.iloc[0])
            up = float((np.diff(tail.values) > 0).mean())
            if growth > 0.25 and up >= 0.65:
                comp["memory_growth"] = float(np.clip(growth / 1.0, 0, 1))
                sig.append(f"memory up {growth*100:.0f}% in {len(tail)} minutes, rising steadily")

    # predictive part: will a limit be crossed soon?
    step_min = step / 60.0
    etas = []
    if "err" in series and name in series["err"].columns and cur.get("err", 1) < slo:
        e = _eta(series["err"][name].dropna(), slo, step_min)
        if e:
            etas.append(e)
    if "p95" in series and name in series["p95"].columns and "p95" in base:
        e = _eta(series["p95"][name].dropna(), max(3 * base["p95"], base["p95"] + 200), step_min)
        if e:
            etas.append(e)
    eta = min(etas) if etas else None
    if eta is not None and eta <= th["breach_horizon_minutes"]:
        comp["trend"] = 0.45
        sig.append(f"trend predicts a limit breach in about {eta:.0f} minutes")

    sev = max(comp.values()) if comp else 0.0
    return {**res, "severity": float(sev), "components": comp, "signals": sig, "eta": eta,
            "anomalous": any(z > zthr for z in zs.values())}


SYMPTOM_TEXT = {
    "traffic_drop": "unreachable unavailable down outage no traffic connection timeout dependency",
    "traffic_spike": "traffic flood surge spike request rate overload",
    "errors": "errors error rate failures failing dependency release change regression",
    "cpu": "cpu saturation high cpu load runaway",
    "memory_growth": "memory leak growth growing steadily",
    "latency": "latency slow response degraded p95",
    "trend": "trend rising degrading",
}
# The cause usually shows first in this order (a flood explains its errors, errors explain their latency)
SYMPTOM_PRIORITY = ["traffic_drop", "traffic_spike", "errors", "cpu", "memory_growth", "latency", "trend"]


def symptom_text(a: dict) -> str:
    """Describe the dominant symptom so the rulebook match is not diluted by secondary effects."""
    present = [k for k in SYMPTOM_PRIORITY if a["components"].get(k, 0) > 0]
    return SYMPTOM_TEXT[present[0]] if present else "anomaly unexplained"


def level_of(sev: float, cfg: dict) -> str:
    cut = cfg["thresholds"]["status_cutoffs"]
    for lvl in ("critical", "high", "medium", "low"):
        if sev >= cut[lvl]:
            return lvl
    return "healthy"


def build_table(series: dict, cfg: dict) -> pd.DataFrame:
    reg = config.services()
    max_cost = max(s["downtime_cost_per_min"] for s in reg.values())
    rows = {}
    for name, meta in reg.items():
        a = analyze_service(name, series, cfg)
        sev = a["severity"]
        lvl = level_of(sev, cfg) if a["has_data"] else "no data"
        cost_norm = max(0.1, meta["downtime_cost_per_min"] / max_cost)
        impact = max(0.1, float(meta["impact"]))
        cur = a["cur"]
        rows[name] = {
            "service": name, "kind": meta.get("kind", "app"), "zone": meta.get("zone", ""),
            "status": lvl, "severity": sev,
            "urgency": 100.0 * sev * cost_norm * impact if lvl not in ("healthy", "no data") else 0.0,
            "cost_norm": cost_norm, "impact": impact,
            "cost_per_min": meta["downtime_cost_per_min"],
            "exposure_per_min": meta["downtime_cost_per_min"] * sev if lvl not in ("healthy", "no data") else 0.0,
            "rps": cur.get("rps"), "err_ratio": cur.get("err"), "p95_ms": cur.get("p95"),
            "cpu": cur.get("cpu"), "mem_mib": cur.get("mem"),
            "failed_per_min": (cur["rps"] * cur["err"]) if "rps" in cur and "err" in cur else None,
            "z_max": max(a["z"].values()) if a["z"] else None, "eta_min": a["eta"],
            "signals": a["signals"], "components": a["components"], "symptom": symptom_text(a),
            "anomalous": a["anomalous"], "has_data": a["has_data"], "hint": "",
        }
    # root-cause hint: a dependency that is at least as unhealthy explains its callers
    for name, r in rows.items():
        if r["severity"] < 0.3:
            continue
        for dep in reg[name].get("depends_on", []):
            d = rows.get(dep)
            if d and d["has_data"] and d["severity"] >= 0.4 and d["severity"] >= 0.8 * r["severity"]:
                r["hint"] = f"Likely cause downstream: {dep} ({'; '.join(d['signals'][:2]) or 'degraded'})"
                break
    df = pd.DataFrame(rows.values())
    if not df.empty:
        df["_ord"] = df["status"].map({s: i for i, s in enumerate(LEVELS + ["no data"])})
        df = df.sort_values(["urgency", "severity"], ascending=False).reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------- incident lifecycle
def update_incidents(table: pd.DataFrame, cfg: dict) -> list[str]:
    """Open / update / close incidents from the latest table. Returns ids of newly created work-orders."""
    th = cfg["thresholds"]
    new_wos: list[str] = []
    open_by_svc = {r["service"]: r for r in store.q("SELECT * FROM incidents WHERE status='open'")}
    for _, row in table.iterrows():
        if not row["has_data"]:
            continue
        svc, sev = row["service"], float(row["severity"])
        inc = open_by_svc.get(svc)
        if inc is None:
            if sev >= th["open_severity"]:
                cnt = int(store.kv_get(f"open_cnt:{svc}", 0)) + 1
                store.kv_set(f"open_cnt:{svc}", cnt)
                if cnt >= th["confirm_points"]:
                    store.kv_set(f"open_cnt:{svc}", 0)
                    new_wos.append(_open_incident(row.to_dict(), cfg))
            else:
                store.kv_set(f"open_cnt:{svc}", 0)
        else:
            store.x("UPDATE incidents SET severity=?, urgency=?, level=?, signals=?, hint=? WHERE id=?",
                    (sev, float(row["urgency"]), row["status"], "|".join(row["signals"]), row["hint"], inc["id"]))
            if sev < th["close_severity"]:
                cnt = int(store.kv_get(f"close_cnt:{svc}", 0)) + 1
                store.kv_set(f"close_cnt:{svc}", cnt)
                if cnt >= th["confirm_points"]:
                    store.kv_set(f"close_cnt:{svc}", 0)
                    _close_incident(inc["id"], svc)
            else:
                store.kv_set(f"close_cnt:{svc}", 0)
    return [w for w in new_wos if w]


def _open_incident(row: dict, cfg: dict) -> str:
    entry, score, trusted = rulebook.best_for(row["symptom"], row["service"])
    opened = store.now()
    err0 = row["err_ratio"] if row["err_ratio"] is not None else 0.0
    proactive = int(err0 < cfg["thresholds"]["error_ratio_slo"])
    iid = store.x(
        "INSERT INTO incidents(service,opened_at,status,severity,urgency,level,signals,runbook_id,match_score,"
        "proactive,err_at_detection,hint) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["service"], opened, "open", row["severity"], row["urgency"], row["status"],
         "|".join(row["signals"]), entry.id, score, proactive, err0, row["hint"]))
    store.audit("system", "incident_opened", f"INC-{iid}", {"service": row["service"], "runbook": entry.id,
                                                            "proactive": bool(proactive), "severity": row["severity"]})
    for inj in store.q("SELECT id, scenario FROM injections WHERE detected_at IS NULL AND ended_at IS NULL"):
        sc = next((s for s in config.scenarios() if s["id"] == inj["scenario"]), None)
        if sc and row["service"] in sc["services"]:
            store.x("UPDATE injections SET detected_at=?, incident_id=? WHERE id=?", (opened, iid, inj["id"]))
    return workorders.create(iid, row, entry, score, trusted, opened)


def _close_incident(iid: int, svc: str) -> None:
    ts = store.now()
    store.x("UPDATE incidents SET status='closed', closed_at=? WHERE id=?", (ts, iid))
    store.x("UPDATE work_orders SET status='auto_closed' WHERE incident_id=? AND status='proposed'", (iid,))
    store.x("UPDATE injections SET resolved_at=? WHERE incident_id=? AND resolved_at IS NULL", (ts, iid))
    store.audit("system", "incident_closed", f"INC-{iid}", {"service": svc, "reason": "metrics back to normal"})


# ----------------------------------------------------------------------------- entry point
def evaluate() -> Snapshot:
    cfg = config.settings()
    now = datetime.now(timezone.utc)
    p = promlib.Prom(cfg["prometheus_url"])
    ok, msg = p.healthy()
    if not ok:
        return Snapshot(False, msg, now)
    try:
        disc = promlib.discover(p)
        if not disc.get("calls"):
            return Snapshot(False, "Prometheus is reachable but has no span metrics yet. Is the demo running "
                                   "and has it been up for a few minutes?", now, meta={"disc": disc})
        series = fetch_series(p, disc, cfg)
    except promlib.PromError as e:
        return Snapshot(False, str(e), now)
    if "rps" not in series:
        return Snapshot(False, "No request metrics returned yet. Wait a few minutes after starting the demo.",
                        now, meta={"disc": disc})
    table = build_table(series, cfg)
    new_wos = update_incidents(table, cfg)
    return Snapshot(True, "ok", now, table, series, {"disc": disc}, new_wos)

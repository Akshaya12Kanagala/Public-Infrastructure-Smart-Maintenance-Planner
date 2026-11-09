import pandas as pd
import plotly.express as px
import streamlit as st

from core import charts, config, metrics, service, store, ui
from core.ui_colors import COLORS

cfg = config.settings()
st.title("Command Center")
st.caption("Live health, risk and response performance of the monitored digital services. Data: Prometheus, refreshed automatically.")


@st.fragment(run_every=cfg["refresh_seconds"])
def live():
    snap = service.snapshot()
    if not ui.require_data(snap):
        return
    t = snap.table
    if ui.killed():
        ui.banner("<b>Kill switch is ON.</b> Automation is stopped; every action needs a person.", "bad")
    elif ui.automation_mode() == "suggest_only":
        ui.banner("Automation mode: <b>suggest only</b>. The system proposes work-orders but cannot run anything.", "warn")

    open_inc = [i for i in service.incidents() if i.get("status") == "open"]
    rs = metrics.repair_stats()
    live_t = t[t["has_data"]]
    c = st.columns(6)
    c[0].metric("Assets monitored", f"{len(live_t)} / {len(t)}")
    c[1].metric("Open incidents", len(open_inc))
    c[2].metric("Critical + High", int(live_t["status"].isin(["critical", "high"]).sum()))
    c[3].metric("Exposure per minute", ui.money(float(live_t["exposure_per_min"].sum())),
                help="Sum of (downtime cost per minute x severity) over unhealthy services")
    pp = rs["proactive_pct"]
    c[4].metric("Proactive repairs", "n/a" if pp is None else f"{pp*100:.0f}%",
                help="Share of executed repairs done before the service breached its error SLO")
    td = rs["t_detect_to_decision"]
    c[5].metric("Median time to decision", "n/a" if td is None else f"{td:.1f} min",
                help="Detection to approve/reject, over decided work-orders")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Highest urgency now")
        top = t[t["urgency"] > 0].head(6).copy()
        if top.empty:
            st.success("All monitored services are inside their normal range.")
        else:
            top["signals"] = top["signals"].apply(lambda s: "; ".join(s) if s else "trend")
            st.dataframe(
                top[["service", "status", "urgency", "signals"]], hide_index=True, width="stretch",
                column_config={"urgency": st.column_config.ProgressColumn("Urgency", min_value=0,
                                                                            max_value=max(20.0, float(top["urgency"].max())), format="%.1f"),
                               "signals": st.column_config.TextColumn("What the metrics show", width="large")})
    with right:
        st.subheader("Fleet status")
        counts = t["status"].value_counts().reindex(["critical", "high", "medium", "low", "healthy", "no data"], fill_value=0)
        fig = px.bar(x=counts.index, y=counts.values, color=counts.index, color_discrete_map=COLORS,
                     labels={"x": "", "y": "services"})
        fig.update_layout(height=260, showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")

    st.subheader("Entry-point traffic")
    series = service.get_series()
    entry = "frontend-proxy" if "rps" in series and "frontend-proxy" in series["rps"].columns else (
        series["rps"].columns[0] if "rps" in series and len(series["rps"].columns) else None)
    if entry:
        n = max(5, cfg["history_minutes"] * 60 // cfg["step_seconds"])
        g = st.columns(3)
        win = max(2, round(cfg["window_minutes"] * 60 / cfg["step_seconds"]))
        base = round(cfg["baseline_minutes"] * 60 / cfg["step_seconds"])
        for col, (m, ttl, unit, pct, floor) in zip(g, [("rps", f"{entry}: requests per minute", "req/min", False, 0.5),
                                                       ("err", f"{entry}: error ratio", "%", True, 0.005),
                                                       ("p95", f"{entry}: p95 latency", "ms", False, 5.0)]):
            if m in series and entry in series[m].columns:
                col.plotly_chart(charts.timeseries(series[m][entry].iloc[-n:], ttl, unit, cfg["thresholds"]["modified_z"],
                                                   base, win, floor, pct, 230), width="stretch")

    st.subheader("Latest activity")
    rows = store.audit_rows(8)
    if rows:
        st.dataframe(pd.DataFrame(rows)[["ts", "actor", "action", "target"]], hide_index=True, width="stretch")
    else:
        st.caption("No events yet. Incidents, decisions and actions will appear here.")


live()

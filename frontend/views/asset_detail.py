import streamlit as st

from core import charts, config, rulebook, service, ui

st.title("Asset Detail")
cfg = config.settings()
snap = service.snapshot()
if not ui.require_data(snap):
    st.stop()
t = snap.table
names = list(t[t["has_data"]]["service"])
if not names:
    st.warning("No service has enough history yet (needs about 10 minutes of metrics).")
    st.stop()
default = st.session_state.get("selected_service", names[0])
c1, c2 = st.columns([3, 2])
svc = c1.selectbox("Asset", names, index=names.index(default) if default in names else 0)
minutes = c2.radio("Range", [30, 60, 90], index=1, horizontal=True, format_func=lambda m: f"{m} min")
st.session_state["selected_service"] = svc


@st.fragment(run_every=cfg["refresh_seconds"])
def live():
    snap = service.snapshot()
    r = snap.table[snap.table["service"] == svc].iloc[0]
    reg = config.services()[svc]
    st.markdown(f"## {svc} {ui.badge(r['status'])}", unsafe_allow_html=True)
    k = st.columns(5)
    k[0].metric("Urgency", f"{r['urgency']:.1f}")
    k[1].metric("Severity", f"{r['severity']:.2f}")
    k[2].metric("Requests / min", "-" if r["rps"] is None else f"{r['rps']:.0f}")
    k[3].metric("Error ratio", ui.pct(r["err_ratio"], 2))
    k[4].metric("p95 latency", "-" if r["p95_ms"] is None else f"{r['p95_ms']:.0f} ms")
    series = service.get_series()
    n = minutes * 60 // cfg["step_seconds"]
    win = max(2, round(cfg["window_minutes"] * 60 / cfg["step_seconds"]))
    base = round(cfg["baseline_minutes"] * 60 / cfg["step_seconds"])
    z = cfg["thresholds"]["modified_z"]
    specs = [("rps", "Requests per minute", "req/min", False, 0.5), ("err", "Error ratio", "%", True, 0.005),
             ("p95", "p95 latency", "ms", False, 5.0), ("cpu", "CPU", "%", True, 0.02),
             ("mem", "Memory", "MiB", False, 5.0)]
    cols = st.columns(2)
    shown = 0
    for m, title, unit, pct, floor in specs:
        if m in series and svc in series[m].columns:
            cols[shown % 2].plotly_chart(
                charts.timeseries(series[m][svc].iloc[-n:], title, unit, z, base, win, floor, pct), width="stretch",
                key=f"{svc}-{m}")
            shown += 1
    if not shown:
        st.info("No metric series for this asset yet.")
    st.caption("Green band = the service's own normal range (median +/- threshold x scale). Red dots = anomalous points.")

    a, b = st.columns(2)
    with a:
        st.subheader("What the system sees")
        for s in r["signals"] or ["Nothing unusual."]:
            st.markdown(f"- {s}")
        if r["eta_min"]:
            st.warning(f"Trend: a limit may be breached in about {r['eta_min']:.0f} minutes.")
        if r["hint"]:
            st.info(r["hint"])
        e, score, trusted = rulebook.best_for(r["symptom"], svc)
        if r["urgency"] > 0:
            st.markdown(f"**Matching runbook:** {e.id}: {e.title} (score {score:.2f})")
    with b:
        st.subheader("Business context")
        st.markdown(f"- Downtime cost: **{ui.money(reg['downtime_cost_per_min'])}** per minute\n"
                    f"- User impact weight: **{reg['impact']:.2f}**\n- Zone: **{reg.get('zone', '-')}**\n"
                    f"- Depends on: {', '.join(reg.get('depends_on', [])) or 'nothing'}\n"
                    f"- Used by: {', '.join(s for s, m in config.services().items() if svc in m.get('depends_on', [])) or 'nothing'}")
    inc = [i for i in service.incidents() if i.get("service") == svc][:5]
    if inc:
        st.subheader("Recent incidents")
        for i in inc:
            st.markdown(f"- INC-{i['id']} | {i['status']} | opened {ui.ago(i['opened_at'])} | runbook {i.get('runbook_id')}")


live()

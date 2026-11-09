import pandas as pd
import plotly.express as px
import streamlit as st

from core import config, engine, executor, prom as promlib, service, store, ui

st.title("Guardrails & Settings")
cfg = config.settings()
tab_g, tab_a, tab_s, tab_m = st.tabs(["Guardrails", "Audit log", "System status", "Metric explorer"])

with tab_g:
    st.markdown("### Automation mode")
    modes = {"suggest_only": "Suggest only: nothing can run", "approve_each": "Approve each action (recommended)",
             "auto_within_limits": "Automatic within limits (only runbooks marked 'not required')"}
    cur = ui.automation_mode()
    new = st.radio("Mode", list(modes), index=list(modes).index(cur), format_func=modes.get, disabled=not ui.can("settings"))
    if new != cur and ui.can("settings"):
        store.kv_set("automation_mode", new)
        store.audit(ui.actor(), "automation_mode_changed", "automation", {"from": cur, "to": new})
        st.rerun()
    st.markdown("### Kill switch")
    ks = st.toggle("Stop all automation immediately", value=ui.killed(), disabled=not ui.can("killswitch"))
    if ks != ui.killed():
        store.kv_set("kill_switch", ks)
        store.audit(ui.actor(), "kill_switch", "automation", {"on": ks})
        st.rerun()
    st.markdown("### Allow-listed actions and limits")
    ex = cfg["executor"]
    st.dataframe(pd.DataFrame([
        {"Action": "restart", "What it does": "docker compose restart <one named service>", "Guard": "service must be in the registry; rate limited"},
        {"Action": "flag_off", "What it does": "switch one named feature flag to off", "Guard": "flag must exist in the flag file; previous value stored for rollback"},
        {"Action": "anything else", "What it does": "never runs", "Guard": "deletes, wildcards, shell strings and unknown targets are rejected"}]),
        hide_index=True, width="stretch")
    c = st.columns(3)
    c[0].metric("Executor", "enabled" if ex.get("enabled") else "disabled")
    c[1].metric("Max actions / service / hour", ex.get("max_actions_per_service_per_hour", 3))
    c[2].metric("Sandbox folder found", "yes" if ex.get("demo_dir") and __import__("os").path.isdir(ex["demo_dir"]) else "no")
    st.caption("Enable the executor only on the sandbox machine: AIOPS_EXECUTOR_ENABLED=true and AIOPS_DEMO_DIR=<demo folder>.")

with tab_a:
    rows = store.audit_rows(1000)
    if not rows:
        st.info("No events yet.")
    else:
        df = pd.DataFrame(rows)
        a, b = st.columns(2)
        who = a.multiselect("Actor", sorted(df["actor"].unique()))
        act = b.multiselect("Action", sorted(df["action"].unique()))
        if who:
            df = df[df["actor"].isin(who)]
        if act:
            df = df[df["action"].isin(act)]
        st.dataframe(df[["ts", "actor", "action", "target", "detail"]], hide_index=True, width="stretch")
        st.download_button("Download audit log (CSV)", df.to_csv(index=False), file_name="audit_log.csv")

with tab_s:
    p = promlib.Prom(cfg["prometheus_url"])
    ok, msg = p.healthy()
    (st.success if ok else st.error)(f"Prometheus {cfg['prometheus_url']}: {msg}")
    st.write(f"Mode: `{cfg['mode']}`  |  API: `{cfg['api_url']}`")
    if ok:
        try:
            d = promlib.discover(p, force=st.button("Re-run metric discovery"))
            st.markdown("**Metrics found in this Prometheus**")
            st.json(d)
            if not d.get("calls"):
                st.warning("No span-metrics found. Wait a few minutes after starting the demo, or use the Metric explorer.")
            snap = service.snapshot()
            if snap.ok:
                have = snap.table[snap.table["has_data"]]["service"].tolist()
                miss = snap.table[~snap.table["has_data"]]["service"].tolist()
                st.markdown(f"**Registry coverage:** {len(have)} services have live data.")
                if miss:
                    st.caption("No data (not running, minimal mode, or different container/service name): " + ", ".join(miss))
        except promlib.PromError as e:
            st.error(str(e))
    st.markdown("**Thresholds in use**")
    st.json(cfg["thresholds"])

with tab_m:
    st.caption("Run any PromQL against the sandbox Prometheus to explore metrics (useful when demo versions differ).")
    flt = st.text_input("Filter metric names", "")
    if ok:
        try:
            names = [n for n in p.metric_names() if flt.lower() in n.lower()]
            st.caption(f"{len(names)} metric names" + (" (first 60 shown)" if len(names) > 60 else ""))
            st.code("\n".join(names[:60]) or "-")
        except promlib.PromError as e:
            st.error(str(e))
    q = st.text_area("PromQL", f"sum by ({cfg['service_label']}) (rate(traces_span_metrics_calls_total[5m]))", height=70)
    lab = st.text_input("Label to split by", cfg["service_label"])
    mins = st.slider("Minutes of history", 10, 180, 60)
    if st.button("Run query") and ok:
        try:
            df = p.range_by(q, lab, mins, cfg["step_seconds"])
            if df.empty:
                st.warning("No series returned. Check the metric name and the label.")
            else:
                st.plotly_chart(px.line(df), width="stretch")
        except promlib.PromError as e:
            st.error(str(e))

import pandas as pd
import plotly.express as px
import streamlit as st

from core import config, rulebook, service, ui

st.title("Risk Ranking")
st.caption("Maintenance priority = Severity x Downtime cost x User impact. Severity comes from live metrics; "
           "cost and impact come from the service registry (business context).")
cfg = config.settings()


@st.fragment(run_every=cfg["refresh_seconds"])
def live():
    snap = service.snapshot()
    if not ui.require_data(snap):
        return
    t = snap.table
    f1, f2, f3 = st.columns([3, 2, 2])
    levels = f1.multiselect("Status", ["critical", "high", "medium", "low", "healthy", "no data"],
                            default=["critical", "high", "medium", "low"])
    kinds = f2.multiselect("Type", sorted(t["kind"].unique()), default=sorted(t["kind"].unique()))
    q = f3.text_input("Search service")
    v = t[t["status"].isin(levels) & t["kind"].isin(kinds)]
    if q:
        v = v[v["service"].str.contains(q, case=False)]
    if v.empty:
        st.success("Nothing matches these filters. If you expect incidents, widen the status filter.")
    show = pd.DataFrame({
        "Service": v["service"], "Status": v["status"], "Urgency": v["urgency"], "Severity": v["severity"],
        "Cost weight": v["cost_norm"], "Impact": v["impact"],
        "Req/min": v["rps"], "Error %": v["err_ratio"].astype(float) * 100, "p95 ms": v["p95_ms"],
        "CPU %": v["cpu"].astype(float) * 100, "Mem MiB": v["mem_mib"],
        "Breach in (min)": v["eta_min"], "Zone": v["zone"],
        "Why": v["signals"].apply(lambda s: "; ".join(s))})
    ev = st.dataframe(show.reset_index(drop=True), hide_index=True, width="stretch", on_select="rerun",
                      selection_mode="single-row", key="rank_table",
                      column_config={
                          "Urgency": st.column_config.ProgressColumn(min_value=0, max_value=max(20.0, float(show["Urgency"].max() or 0)), format="%.1f"),
                          "Severity": st.column_config.NumberColumn(format="%.2f"),
                          "Cost weight": st.column_config.NumberColumn(format="%.2f"),
                          "Impact": st.column_config.NumberColumn(format="%.2f"),
                          "Req/min": st.column_config.NumberColumn(format="%.0f"),
                          "Error %": st.column_config.NumberColumn(format="%.2f"),
                          "p95 ms": st.column_config.NumberColumn(format="%.0f"),
                          "CPU %": st.column_config.NumberColumn(format="%.0f"),
                          "Mem MiB": st.column_config.NumberColumn(format="%.0f"),
                          "Breach in (min)": st.column_config.NumberColumn(format="%.0f"),
                          "Why": st.column_config.TextColumn(width="large")})
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        svc = show.reset_index(drop=True).iloc[sel[0]]["Service"]
        r = t[t["service"] == svc].iloc[0]
        st.session_state["selected_service"] = svc
        st.markdown(f"### {svc} {ui.badge(r['status'])}", unsafe_allow_html=True)
        a, b = st.columns(2)
        with a:
            st.markdown("**What the metrics show**")
            for s in r["signals"] or ["No anomaly signal"]:
                st.markdown(f"- {s}")
            if r["hint"]:
                st.info(r["hint"])
        with b:
            e, score, trusted = rulebook.best_for(r["symptom"], svc)
            st.markdown(f"**Matched runbook:** {e.id}: {e.title}")
            st.caption(f"Match score {score:.2f}" + ("" if trusted else " (low: escalation runbook used)"))
            st.markdown(f"Estimated effort: ~{e.effort_min} min | Approval: {e.approval}")
        st.page_link("views/asset_detail.py", label="Open charts for this asset", icon=":material/monitoring:")

    with st.expander("How the urgency score is built"):
        st.markdown(
            "- **Severity (0 to 1):** the worst of error ratio, latency, traffic spike or drop, CPU, memory growth and "
            "predicted breach, each computed against the service's own normal behaviour (median and MAD of the last "
            f"{cfg['baseline_minutes']} minutes; outlier threshold {cfg['thresholds']['modified_z']}).\n"
            "- **Cost weight:** downtime cost per minute relative to the most expensive service (config/registry.yaml).\n"
            "- **Impact:** how badly users are harmed when it fails (config/registry.yaml).\n"
            "- **Urgency = 100 x severity x cost weight x impact.** Healthy services score 0.")
        top = t[t["urgency"] > 0].head(8)
        if not top.empty:
            m = top.melt(id_vars="service", value_vars=["severity", "cost_norm", "impact"], var_name="factor")
            fig = px.bar(m, x="service", y="value", color="factor", barmode="group")
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch")


live()

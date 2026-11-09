import pandas as pd
import plotly.express as px
import streamlit as st

from core import metrics, service, ui

st.title("Success Metrics")
st.caption("Computed only from real events recorded by this dashboard: detections, decisions and scenario runs.")
rs, sc = metrics.repair_stats(), metrics.scenario_stats()

st.subheader("1. Increase in proactive repairs")
c = st.columns(4)
c[0].metric("Repairs executed", rs["repaired"])
c[1].metric("Proactive repairs", rs["proactive"], help="Executed before the service breached its error-ratio SLO")
c[2].metric("Proactive share", "n/a" if rs["proactive_pct"] is None else f"{rs['proactive_pct']*100:.0f}%")
c[3].metric("Verified fixes", rs["verified"])
if rs["repaired"]:
    pie = px.pie(names=["Proactive", "Reactive"], values=[rs["proactive"], rs["repaired"] - rs["proactive"]],
                 color=["Proactive", "Reactive"], color_discrete_map={"Proactive": "#2E7D32", "Reactive": "#EF6C00"}, hole=0.5)
    pie.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(pie, width="stretch")
else:
    st.info("No executed repairs yet. Run a scenario in assisted mode and approve the work-order.")

st.subheader("2. Reduced response time for critical incidents")
c = st.columns(4)
f = lambda v: "n/a" if v is None else f"{v:.1f} min"
c[0].metric("Detection delay", f(None if not sc["detect_delay"] else sum(sc["detect_delay"]) / len(sc["detect_delay"])),
            help="From the start of a scenario to the system opening the incident (assisted runs)")
c[1].metric("Detection to decision", f(rs["t_detect_to_decision"]))
c[2].metric("Manual fix (baseline)", f(sc["median_manual"]), help="Median time to resolve when fixed by hand")
c[3].metric("Assisted fix", f(sc["median_assisted"]), help="Median time to resolve with the system")
if sc["ttr_manual"] and sc["ttr_assisted"]:
    d = pd.DataFrame({"run type": ["Manual"] * len(sc["ttr_manual"]) + ["Assisted"] * len(sc["ttr_assisted"]),
                      "minutes to resolve": sc["ttr_manual"] + sc["ttr_assisted"]})
    st.plotly_chart(px.box(d, x="run type", y="minutes to resolve", points="all", color="run type"), width="stretch")
    gain = (sc["median_manual"] - sc["median_assisted"]) / sc["median_manual"] * 100 if sc["median_manual"] else 0
    st.success(f"Median response time changed by {gain:.0f}% (n = {len(sc['ttr_manual'])} manual, {len(sc['ttr_assisted'])} assisted).")
    st.caption("Small samples: repeat each scenario several times before quoting a percentage.")
else:
    st.info("To measure the improvement, run each scenario both ways in the Scenario Lab: once as 'Manual baseline' "
            "and once as 'Assisted'.")

st.subheader("Work-order timings (median)")
st.table(pd.DataFrame({"Step": ["Detected to decision", "Decision to action", "Detected to repair"],
                       "Minutes": [rs["t_detect_to_decision"], rs["t_decision_to_action"], rs["t_detect_to_repair"]]}
                      ).fillna("n/a"))

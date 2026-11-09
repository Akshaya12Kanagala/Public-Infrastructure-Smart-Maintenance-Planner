import json

import pandas as pd
import streamlit as st

from core import service, store, ui

st.title("Incidents")
st.caption("Every incident is opened automatically from live metrics, matched to a runbook, and linked to a work-order.")
snap = service.snapshot()
if not ui.require_data(snap):
    st.stop()

inc = service.incidents()
if not inc:
    st.success("No incidents recorded yet. Start a scenario in the Scenario Lab to see the full flow.")
    st.stop()
wos = {w["incident_id"]: w for w in service.work_orders() if w.get("incident_id") is not None}
tab_open, tab_closed = st.tabs(["Open", "Closed"])


def timeline(i: dict, w: dict | None) -> list[tuple[str, str | None]]:
    ev = [("Detected by the system", i["opened_at"])]
    if w:
        ev += [("Work-order proposed", w["created_at"]), ("Decision (approve / reject)", w.get("decided_at")),
               ("Remedy executed", w.get("executed_at")), ("Verified", w.get("verified_at"))]
    ev.append(("Incident closed (metrics normal)", i.get("closed_at")))
    return ev


def card(i: dict):
    w = wos.get(i["id"])
    sigs = [s for s in (i.get("signals") or "").split("|") if s]
    head = f"INC-{i['id']}  |  {i['service']}  |  {i.get('level', '')}  |  opened {ui.ago(i['opened_at'])}"
    with st.expander(head, expanded=(i["status"] == "open")):
        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown(f"{ui.badge(i.get('level', 'low'))} &nbsp; severity **{i['severity']:.2f}**, urgency **{i['urgency']:.1f}**",
                        unsafe_allow_html=True)
            for s in sigs or ["Trend-based detection"]:
                st.markdown(f"- {s}")
            if i.get("hint"):
                st.info(i["hint"])
            st.markdown(f"**Runbook:** {i.get('runbook_id')} (match score {float(i.get('match_score') or 0):.2f})")
            st.markdown("**Detected before the SLO was breached (proactive):** " + ("yes" if i.get("proactive") else "no, users were already affected"))
        with c2:
            st.markdown("**Timeline**")
            for label, ts in timeline(i, w):
                st.markdown(f"- {'done' if ts else 'pending'}: {label}" + (f" ({ui.ago(ts)})" if ts else ""))
            if w:
                st.markdown(f"Work-order: **{w['id']}** ({w['status']})")
                st.page_link("views/work_orders.py", label="Open work-orders", icon=":material/assignment:")


with tab_open:
    rows = [i for i in inc if i["status"] == "open"]
    if not rows:
        st.success("No open incidents.")
    for i in rows:
        card(i)
with tab_closed:
    rows = [i for i in inc if i["status"] != "open"]
    if rows:
        df = pd.DataFrame(rows)[["id", "service", "level", "opened_at", "closed_at", "runbook_id", "proactive"]]
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.caption("Closed incidents will be listed here.")

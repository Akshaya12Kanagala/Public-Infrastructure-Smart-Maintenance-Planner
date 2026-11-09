import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from core import executor, service, store, ui, workorders

st.title("Work Orders")
st.caption("Generated automatically from incidents and the rulebook. A person approves; the system never decides alone.")
snap = service.snapshot()
if not ui.require_data(snap):
    st.stop()
wos = service.work_orders()
if not wos:
    st.info("No work-orders yet. They appear automatically when an incident opens.")
    st.stop()

f1, f2 = st.columns([2, 3])
status = f1.multiselect("Status", sorted({w["status"] for w in wos}),
                        default=[s for s in sorted({w["status"] for w in wos}) if s in ("proposed", "approved", "executed", "needs_attention")] or None)
view = [w for w in wos if not status or w["status"] in status]
if not view:
    st.caption("No work-orders with this status.")
    st.stop()
tbl = pd.DataFrame([{"Work-order": w["id"], "Service": w["payload"]["service"], "Priority": w["payload"]["priority"],
                     "Status": w["status"], "Runbook": w["payload"]["runbook"]["id"],
                     "Effort (min)": w["payload"]["estimate"]["effort_min"], "Created": ui.ago(w["created_at"]),
                     "Owner": w.get("assignee") or "-"} for w in view])
ev = st.dataframe(tbl, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="wo_tbl")
sel = ev.selection.rows if ev and ev.selection else []
wo = view[sel[0]] if sel else view[0]
p = wo["payload"]
due = store.parse_ts(p["sla_due"])
mins_left = (due - datetime.now(timezone.utc)).total_seconds() / 60

st.divider()
st.markdown(f"## {wo['id']}  {ui.badge(p['level'])}", unsafe_allow_html=True)
st.markdown(f"**{p['title']}**  |  status: `{wo['status']}`")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Priority", p["priority"])
s2.metric("Estimated effort", f"~{p['estimate']['effort_min']} min")
s3.metric("Decision due in", f"{mins_left:.0f} min" if mins_left > 0 else "overdue",
          delta=None if wo["decided_at"] else f"target {p['sla_minutes']} min", delta_color="off")
s4.metric("Approval", p["estimate"]["approval"])

t1, t2, t3, t4 = st.tabs(["Overview", "Estimated repair requirements", "Action & approval", "Audit"])
with t1:
    st.write(p["summary"])
    if p.get("hint"):
        st.info(p["hint"])
    st.markdown("**Evidence from live metrics**")
    for s in p["evidence"] or ["Trend-based detection"]:
        st.markdown(f"- {s}")
    r = p["runbook"]
    st.markdown(f"**Source:** runbook {r['id']}: {r['title']} (match score {r['match_score']})"
                + ("" if r["trusted"] else "  (low confidence: escalation runbook)"))
with t2:
    e = p["estimate"]
    st.table(pd.DataFrame({"Item": ["Estimated effort", "Resources needed", "Approval", "Risk level", "Service owner SLA"],
                           "Value": [f"about {e['effort_min']} minutes", e["resources"], e["approval"], e["risk"],
                                     f"decision within {p['sla_minutes']} minutes"]}).set_index("Item"))
    st.markdown("**Steps (from the rulebook)**")
    for i, s in enumerate(p["steps"], 1):
        st.markdown(f"{i}. {s}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Safety limits**")
        [st.markdown(f"- {x}") for x in p["safety_limits"]]
        st.markdown("**Verify**")
        [st.markdown(f"- {x}") for x in p["verify"]]
    with c2:
        st.markdown("**Rollback**")
        [st.markdown(f"- {x}") for x in p["rollback"]]
        st.markdown("**Escalate if**")
        [st.markdown(f"- {x}") for x in p["escalate_if"]]
    if p["mishap"]:
        with st.expander("Known mishaps for this situation"):
            [st.markdown(f"- {x}") for x in p["mishap"]]
with t3:
    plan = p["plan"]
    st.markdown(f"**Planned action:** {plan['reason']}")
    st.code(plan["command"], language="bash")
    ok, why = executor.can_execute(plan)
    if not ok:
        st.caption(f"Automatic execution unavailable: {why}")


    @st.dialog("Confirm remedy")
    def confirm_run():
        st.write("This will run in the **sandbox** environment:")
        st.code(plan["command"], language="bash")
        agree = st.checkbox("I confirm this target is the sandbox and the action is correct")
        if st.button("Approve and run", type="primary", disabled=not agree):
            res = service.decide(wo["id"], "approve", reason, ui.actor(), execute=True)
            st.session_state["wo_msg"] = ("success" if res["ok"] else "error", res.get("output", ""))
            st.rerun()


    if wo["status"] in ("proposed", "approved"):
        reason = st.text_input("Reason / note for the audit trail", key=f"reason-{wo['id']}")
        b1, b2, b3 = st.columns(3)
        if b1.button("Approve and run", type="primary", disabled=not (ok and ui.can("approve"))):
            confirm_run()
        if b2.button("Approve (I run it myself)", disabled=not ui.can("approve")):
            res = service.decide(wo["id"], "approve", reason, ui.actor(), execute=False)
            st.session_state["wo_msg"] = ("success", "Approved. Run the command above, then press 'Mark as executed'.")
            st.rerun()
        if b3.button("Reject", disabled=not ui.can("approve")):
            if not reason.strip():
                st.warning("Please enter a reason for the rejection.")
            else:
                service.decide(wo["id"], "reject", reason, ui.actor())
                st.rerun()
        if not ui.can("approve"):
            st.caption("Only the admin role can approve or reject.")
    if wo["status"] == "approved" and ui.can("approve"):
        if st.button("Mark as executed (I ran the command)"):
            service.mark_done_manually(wo["id"], ui.actor())
            st.rerun()
    if wo["status"] in ("executed", "needs_attention", "verified", "rolled_back"):
        ex = wo.get("execution") or {}
        st.markdown(f"**Executed** {ui.ago(wo.get('executed_at'))}: {'ok' if ex.get('ok') else 'failed'}")
        if ex.get("output"):
            st.code(str(ex["output"])[:1200])
        v1, v2 = st.columns(2)
        if v1.button("Verify result now"):
            res = service.verify(wo["id"], ui.actor())
            st.session_state["wo_msg"] = ("info", f"Verification: {json.dumps(res)}")
            st.rerun()
        if v2.button("Roll back", disabled=not ui.can("approve") or plan["type"] != "flag_off"):
            res = service.rollback(wo["id"], ui.actor())
            st.session_state["wo_msg"] = ("info", res["output"])
            st.rerun()
        if wo.get("verification"):
            vr = wo["verification"]
            (st.success if vr["state"] == "verified" else st.warning)(
                f"Verification: {vr['state']} (severity {vr['severity_before']:.2f} -> {vr['severity_now']:.2f})")
    msg = st.session_state.pop("wo_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    if ui.can("assign"):
        a1, a2 = st.columns([3, 1])
        who = a1.text_input("Assign to", value=wo.get("assignee") or "", key=f"as-{wo['id']}")
        if a2.button("Assign") and who:
            service.assign(wo["id"], who, ui.actor())
            st.rerun()
    d1, d2 = st.columns(2)
    d1.download_button("Download as Markdown", workorders.to_markdown(wo), file_name=f"{wo['id']}.md")
    d2.download_button("Download as JSON", json.dumps(wo, indent=2, default=str), file_name=f"{wo['id']}.json")
with t4:
    rows = [r for r in store.audit_rows(500) if r["target"] == wo["id"] or r["target"].startswith("INC-")]
    rows = [r for r in rows if r["target"] == wo["id"]]
    st.dataframe(pd.DataFrame(rows)[["ts", "actor", "action", "detail"]] if rows else pd.DataFrame(),
                 hide_index=True, width="stretch")

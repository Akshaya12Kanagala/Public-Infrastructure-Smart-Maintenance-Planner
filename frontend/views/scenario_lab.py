import pandas as pd
import streamlit as st

from core import config, executor, service, store, ui

st.title("Scenario Lab")
st.caption("Real incidents on a real running system. Each scenario switches on a genuine failure mode of the "
           "OpenTelemetry demo (feature flag), and the dashboard must detect it and propose the rulebook fix.")
cfg = config.settings()
L = cfg["links"]
l = st.columns(5)
for col, (k, label) in zip(l, [("shop", "Shop"), ("feature_flags", "Feature flags"), ("load_generator", "Load generator"),
                               ("jaeger", "Traces"), ("prometheus", "Prometheus")]):
    col.link_button(label, L[k], width="stretch")

flags = executor.read_flags()
if flags is None:
    ui.banner("<b>Flag file not found on this machine.</b> You can still run scenarios: switch the flag on in the Feature "
              "Flag UI, then press the matching 'I switched it on' button below so the timing is recorded. "
              "To control flags from here, set AIOPS_DEMO_DIR to the demo folder.", "warn")
else:
    st.success(f"Connected to the demo's flag file ({len(flags)} flags). Scenarios are validated against it.")

mode = st.radio("How will this run be handled?", ["assisted", "manual"], horizontal=True,
                format_func=lambda m: {"assisted": "Assisted: the system detects and proposes the fix",
                                       "manual": "Manual baseline: fix it by hand, no system help"}[m],
                help="Manual runs give the baseline response time that the assisted runs are compared with.")
st.divider()

active = store.q("SELECT * FROM injections WHERE ended_at IS NULL")
active_ids = {a["scenario"] for a in active}
cols = st.columns(2)
for i, sc in enumerate(config.scenarios()):
    with cols[i % 2]:
        with st.container(border=True):
            st.markdown(f"#### {sc['name']}")
            st.caption(f"flag `{sc['flag']}` = `{sc['variant']}`  |  runbook {sc['runbook']}")
            st.markdown(f"**Real-world analogue:** {sc['analog']}")
            st.markdown(f"**Expected signals:** {sc['expected_signals']}")
            st.markdown(f"**Affects:** {', '.join(sc['services'])}")
            exists = flags is None or (sc["flag"] in flags and sc["variant"] in flags[sc["flag"]].get("variants", {}))
            if not exists:
                st.warning("This flag or variant does not exist in your demo version. Check the flag file.")
            if sc["id"] in active_ids:
                st.info("Running")
            if st.button("Start scenario" if flags is not None else "I switched it on", key=f"go-{sc['id']}",
                         disabled=(not ui.can("lab")) or (sc["id"] in active_ids) or not exists, width="stretch"):
                prev = None
                if flags is not None:
                    ok, msg, prev = executor.set_flag(sc["flag"], sc["variant"])
                    if not ok:
                        st.error(msg)
                        st.stop()
                store.x("INSERT INTO injections(scenario,flag,variant,previous,mode,started_at) VALUES(?,?,?,?,?,?)",
                        (sc["id"], sc["flag"], sc["variant"], prev, mode, store.now()))
                store.audit(ui.actor(), "scenario_started", sc["id"], {"flag": sc["flag"], "variant": sc["variant"], "mode": mode})
                st.rerun()

st.divider()
st.subheader("Running scenarios")
st.caption("After pressing Start, confirm in the Feature Flag UI that the flag shows as on. Metrics react within 1 to 3 minutes (the demo exports about once a minute).")
if not active:
    st.caption("None running.")
for a in active:
    c1, c2, c3 = st.columns([4, 2, 2])
    c1.markdown(f"**{a['scenario']}**  ({a['mode']}), started {ui.ago(a['started_at'])}"
                + (f", detected {ui.ago(a['detected_at'])}" if a["detected_at"] else ", not detected yet"))
    label = "Fix it by hand: switch off" if a["mode"] == "manual" else "Stop scenario"
    if c2.button(label, key=f"stop-{a['id']}", disabled=not ui.can("lab")):
        if executor.flagd_path() is not None:
            executor.set_flag(a["flag"], a["previous"] or "off")
        now = store.now()
        store.x("UPDATE injections SET ended_at=?, resolved_at=COALESCE(resolved_at, ?) WHERE id=?",
                (now, now if a["mode"] == "manual" else None, a["id"]))
        store.audit(ui.actor(), "scenario_stopped", a["scenario"], {"mode": a["mode"]})
        st.rerun()

st.subheader("Run history")
hist = store.q("SELECT * FROM injections ORDER BY id DESC LIMIT 30")
if hist:
    df = pd.DataFrame(hist)
    df["time to detect (min)"] = [ui.minutes_between(r["started_at"], r["detected_at"]) for r in hist]
    df["time to resolve (min)"] = [ui.minutes_between(r["started_at"], r["resolved_at"]) for r in hist]
    st.dataframe(df[["id", "scenario", "mode", "started_at", "time to detect (min)", "time to resolve (min)"]],
                 hide_index=True, width="stretch")
else:
    st.caption("Runs will be listed here and feed the Success Metrics page.")

with st.expander("What a company does vs what this system does"):
    st.markdown(
        "**Without the system:** an alert fires late (or a customer complains), an engineer logs in, looks through "
        "dashboards and logs, guesses the cause, and runs a fix by hand, sometimes with a wrong command.\n\n"
        "**With the system:** the anomaly is detected from the service's own baseline (sometimes before the SLO is "
        "breached), the matching runbook is retrieved with its safety limits, a work-order with the estimated repair "
        "requirements is generated, a person approves, the allow-listed action runs, and the result is verified or "
        "rolled back. Every step is in the audit trail.")

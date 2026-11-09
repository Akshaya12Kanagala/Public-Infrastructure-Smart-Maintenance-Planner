"""Shared UI helpers: CSS, badges, role handling, empty states."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from . import config, store

from .ui_colors import COLORS  # noqa: E402
PERMS = {
    "viewer": {"view"},
    "engineer": {"view", "assign", "lab", "edit"},
    "admin": {"view", "assign", "lab", "edit", "approve", "execute", "settings", "killswitch"},
}
CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1400px;}
.badge {display:inline-block; padding:2px 10px; border-radius:12px; color:#fff; font-size:0.78rem; font-weight:600;}
.card {border:1px solid rgba(128,128,128,.28); border-radius:10px; padding:14px 16px; margin-bottom:10px;}
.card h4 {margin:0 0 6px 0;}
.muted {color: rgba(128,128,128,.95); font-size:0.85rem;}
.banner {border-radius:8px; padding:10px 14px; margin-bottom:12px; font-size:0.92rem;}
.banner.warn {background:rgba(239,108,0,.14); border:1px solid rgba(239,108,0,.5);}
.banner.bad {background:rgba(198,40,40,.14); border:1px solid rgba(198,40,40,.5);}
.banner.ok {background:rgba(46,125,50,.12); border:1px solid rgba(46,125,50,.45);}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(status: str) -> str:
    return f'<span class="badge" style="background:{COLORS.get(status, "#757575")}">{status.upper()}</span>'


def banner(text: str, kind: str = "warn") -> None:
    st.markdown(f'<div class="banner {kind}">{text}</div>', unsafe_allow_html=True)


def role() -> str:
    return st.session_state.get("role", "viewer")


def actor() -> str:
    return f"{st.session_state.get('user', 'user')} ({role()})"


def can(perm: str) -> bool:
    return perm in PERMS.get(role(), set())


def automation_mode() -> str:
    return store.kv_get("automation_mode", config.settings()["automation"]["default_mode"])


def killed() -> bool:
    return bool(store.kv_get("kill_switch", False))


def money(x: float | None) -> str:
    cur = config.settings().get("currency", "")
    return "-" if x is None else f"{cur} {x:,.0f}"


def pct(x: float | None, nd: int = 1) -> str:
    return "-" if x is None else f"{x*100:.{nd}f}%"


def ago(iso: str | None) -> str:
    if not iso:
        return "-"
    d = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    if d < 90:
        return f"{int(d)} s ago"
    if d < 5400:
        return f"{int(d/60)} min ago"
    if d < 172800:
        return f"{d/3600:.1f} h ago"
    return f"{d/86400:.1f} days ago"


def minutes_between(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60


def need(perm: str, what: str = "this action") -> bool:
    if can(perm):
        return True
    st.info(f"Your role ({role()}) cannot do {what}. Switch role in the sidebar (in api mode the backend enforces this).")
    return False


def require_data(snap) -> bool:
    """Show an honest empty state instead of fake numbers when there is no live data."""
    if snap.ok and not snap.table.empty:
        return True
    banner(f"<b>No live data.</b> {snap.message}", "bad")
    st.markdown(
        "This dashboard shows **only real telemetry**. Start the sandbox environment first "
        "(see `docs/environment/ENVIRONMENT_SETUP.md`), wait 5 to 10 minutes for metrics, then reload.\n\n"
        f"- Prometheus expected at `{config.settings()['prometheus_url']}`\n"
        "- Check **Guardrails & Settings > System status** for details and the Metric Explorer.")
    return False


def sidebar(snap) -> None:
    with st.sidebar:
        st.markdown("### Smart Maintenance Planner")
        st.caption("Digital infrastructure control room")
        st.session_state.setdefault("user", "operator")
        st.session_state.setdefault("role", "admin")
        st.text_input("Operator name", key="user")
        st.selectbox("Role", ["viewer", "engineer", "admin"], key="role",
                     help="Local preview roles. In api mode the backend's JWT roles apply.")
        st.divider()
        st.caption(f"Mode: **{config.settings()['mode']}** | Automation: **{automation_mode().replace('_', ' ')}**")
        if killed():
            st.error("KILL SWITCH ON: automation stopped")
        if snap.ok:
            st.success("Live data connected")
        else:
            st.warning("No live data")
        st.caption(f"Updated {snap.ts:%H:%M:%S} UTC")

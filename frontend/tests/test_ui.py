"""Smoke tests: every page renders without an exception, both with live data and without."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")

PAGES = ["views/command_center.py", "views/risk_ranking.py", "views/asset_detail.py", "views/incidents.py",
         "views/work_orders.py", "views/map_graph.py", "views/assistant.py", "views/rulebook_page.py",
         "views/scenario_lab.py", "views/success_metrics.py", "views/governance.py"]


def open_page(page: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.switch_page(page)
    at.run()
    return at


@pytest.fixture()
def live(env):
    from core import engine
    engine.evaluate()
    engine.evaluate()  # opens incidents + work-orders from the injected faults
    import streamlit as st
    st.cache_data.clear()
    return env


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_live_data(live, page):
    at = open_page(page)
    assert not at.exception, [e.value for e in at.exception]


def test_empty_state_without_prometheus(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOPS_PROM_URL", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.setenv("AIOPS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIOPS_MODE", "local")
    from core import config, prom
    config.reset_caches(); prom._disc_cache.clear()
    import streamlit as st
    st.cache_data.clear()
    for page in ["views/command_center.py", "views/risk_ranking.py", "views/work_orders.py"]:
        at = open_page(page)
        assert not at.exception, [e.value for e in at.exception]
        text = " ".join(m.value for m in at.markdown)
        assert "No live data" in text
    config.reset_caches()


def test_work_order_approve_without_execution(live):
    at = open_page("views/work_orders.py")
    labels = [b.label for b in at.button]
    assert "Approve (I run it myself)" in labels
    next(b for b in at.button if b.label == "Approve (I run it myself)").click().run()
    assert not at.exception, [e.value for e in at.exception]
    from core import store
    assert any(r["status"] == "approved" for r in store.q("SELECT status FROM work_orders"))
    assert any(r["action"] == "work_order_approved" for r in store.audit_rows())


def test_viewer_cannot_approve(live):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.session_state["role"] = "viewer"
    at.switch_page("views/work_orders.py")
    at.run()
    btn = next(b for b in at.button if b.label == "Approve (I run it myself)")
    assert btn.disabled


def test_assistant_answers_from_rulebook(live):
    at = open_page("views/assistant.py")
    at.chat_input[0].set_value("How do I handle a memory leak?").run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.chat_message[-1].markdown)
    assert "RB-105" in text

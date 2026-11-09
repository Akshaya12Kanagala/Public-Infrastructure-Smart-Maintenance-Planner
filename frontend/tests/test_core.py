import json

from core import config, engine, executor, rulebook, store


def run_twice():
    engine.evaluate()
    return engine.evaluate()


def test_rulebook_parses_and_matches():
    entries, extras = rulebook.load()
    assert [e.id for e in entries][:3] == ["RB-101", "RB-102", "RB-103"]
    assert len(entries) == 8 and len(extras) >= 2
    e, score, trusted = rulebook.best_for("memory leak growth growing steadily", "email")
    assert e.id == "RB-105" and trusted
    e, score, trusted = rulebook.best_for("zzzz qqqq", "")
    assert e.id == "RB-108" and not trusted


def test_engine_detects_injected_faults(env):
    snap = run_twice()
    assert snap.ok, snap.message
    t = snap.table.set_index("service")
    assert t.loc["cart", "status"] in ("critical", "high")
    assert t.loc["ad", "components"].get("cpu", 0) > 0.5
    assert "memory_growth" in t.loc["email", "components"]
    assert "traffic_drop" in t.loc["payment", "components"]
    assert t.loc["frontend", "status"] in ("healthy", "low")
    # business weighting: payment/checkout outrank ad even though ad is also failing
    assert t.loc["payment", "urgency"] > t.loc["ad", "urgency"]
    # root cause hint: checkout depends on payment and cart
    assert "downstream" in t.loc["checkout", "hint"] or t.loc["checkout", "severity"] < 0.3


def test_incidents_and_work_orders_created(env):
    run_twice()
    inc = {i["service"]: i for i in store.q("SELECT * FROM incidents")}
    assert {"cart", "ad", "email", "payment"} <= set(inc)
    assert inc["cart"]["runbook_id"] == "RB-102"
    assert inc["payment"]["runbook_id"] == "RB-103"
    assert inc["ad"]["runbook_id"] == "RB-104"
    assert inc["email"]["runbook_id"] == "RB-105"
    wo = store.q("SELECT * FROM work_orders")
    assert len(wo) >= 4
    p = json.loads(wo[0]["payload"])
    assert p["estimate"]["effort_min"] > 0 and p["steps"] and p["plan"]["command"]
    # idempotent: a third evaluation does not duplicate open incidents
    n = len(store.q("SELECT * FROM incidents"))
    engine.evaluate()
    assert len(store.q("SELECT * FROM incidents")) == n


def test_proactive_flag(env):
    run_twice()
    inc = {i["service"]: i for i in store.q("SELECT * FROM incidents")}
    assert inc["email"]["proactive"] == 1       # memory growth, no errors yet
    assert inc["cart"]["proactive"] == 0        # users already seeing errors


def test_executor_guardrails(env, tmp_path, monkeypatch):
    plan = {"type": "restart", "target": "cart", "command": "x"}
    ok, why = executor.can_execute(plan)
    assert not ok and "disabled" in why
    demo = tmp_path / "demo"
    (demo / "src" / "flagd").mkdir(parents=True)
    (demo / "src" / "flagd" / "demo.flagd.json").write_text(json.dumps({"flags": {
        "cartFailure": {"state": "ENABLED", "variants": {"off": False, "50%": 0.5}, "defaultVariant": "50%"}}}))
    monkeypatch.setenv("AIOPS_DEMO_DIR", str(demo))
    monkeypatch.setenv("AIOPS_EXECUTOR_ENABLED", "true")
    config.reset_caches()
    assert executor.can_execute({"type": "restart", "target": "cart; rm -rf /"})[0] is False
    assert executor.can_execute({"type": "restart", "target": "not-a-service"})[0] is False
    assert executor.can_execute({"type": "flag_off", "target": "nope"})[0] is False
    flag_plan = {"type": "flag_off", "target": "cartFailure", "command": "x"}
    assert executor.can_execute(flag_plan)[0] is True
    res = executor.execute(flag_plan, "tester")
    assert res["ok"] and res["previous"] == "50%"
    assert executor.read_flags()["cartFailure"]["defaultVariant"] == "off"
    assert executor.rollback(flag_plan, res["previous"], "tester")["ok"]
    assert executor.read_flags()["cartFailure"]["defaultVariant"] == "50%"
    store.kv_set("kill_switch", True)
    assert executor.can_execute(flag_plan)[0] is False
    store.kv_set("kill_switch", False)
    for _ in range(3):
        executor.execute(flag_plan, "tester")
    assert "Rate limit" in executor.can_execute(flag_plan)[1]

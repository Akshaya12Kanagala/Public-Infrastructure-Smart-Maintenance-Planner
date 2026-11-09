"""Check that the sandbox is ready:  python scripts/check_environment.py
Reports Prometheus reachability, discovered metric names, which registry services have data, and the flag file."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from core import config, engine, executor, prom  # noqa: E402

cfg = config.settings()
p = prom.Prom(cfg["prometheus_url"])
ok, msg = p.healthy()
print(f"[{'OK' if ok else 'FAIL'}] Prometheus {cfg['prometheus_url']}: {msg}")
if not ok:
    sys.exit(1)
d = prom.discover(p, force=True)
for k in ("calls", "bucket", "cpu", "mem", "kafka_lag"):
    print(f"[{'OK' if d.get(k) else '--'}] {k}: {d.get(k)}")
print("     span kind filter:", d.get("kind_filter") or "(none)", "| latency unit:", d.get("latency_unit"))
series = engine.fetch_series(p, d, cfg)
have = sorted(series.get("rps", {}).columns) if "rps" in series else []
print(f"[{'OK' if have else 'FAIL'}] services with request metrics: {len(have)}")
missing = [s for s in config.services() if s not in have]
print("     registry services without data:", ", ".join(missing) or "none")
flags = executor.read_flags()
print(f"[{'OK' if flags else '--'}] flag file:", executor.flagd_path() or "not configured (set AIOPS_DEMO_DIR)")
if flags:
    print("     flags found:", len(flags))
    for sc in config.scenarios():
        status = "ok" if sc["flag"] in flags and sc["variant"] in flags[sc["flag"]]["variants"] else "MISSING in this version"
        print(f"       - {sc['id']}: {sc['flag']}={sc['variant']} -> {status}")

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


@pytest.fixture(scope="session")
def prom_url():
    import fake_prom
    srv, url = fake_prom.start()
    yield url
    srv.shutdown()


@pytest.fixture()
def env(tmp_path, prom_url, monkeypatch):
    monkeypatch.setenv("AIOPS_PROM_URL", prom_url)
    monkeypatch.setenv("AIOPS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIOPS_MODE", "local")
    monkeypatch.delenv("AIOPS_DEMO_DIR", raising=False)
    monkeypatch.delenv("AIOPS_EXECUTOR_ENABLED", raising=False)
    from core import config, prom
    config.reset_caches()
    prom._disc_cache.clear()
    yield tmp_path
    config.reset_caches()

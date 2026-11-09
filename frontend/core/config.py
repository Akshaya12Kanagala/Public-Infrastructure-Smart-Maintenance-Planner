"""Configuration loading: YAML files + environment overrides. No Streamlit imports (testable)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    return Path(os.environ.get("AIOPS_CONFIG_DIR", ROOT / "config"))


def data_dir() -> Path:
    p = Path(os.environ.get("AIOPS_DATA_DIR", ROOT / "data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def rulebook_path() -> Path:
    return Path(os.environ.get("AIOPS_RULEBOOK", ROOT / "knowledge" / "rulebook.md"))


def _yaml(name: str) -> dict:
    with open(config_dir() / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def settings() -> dict:
    s = _yaml("settings.yaml")
    env = os.environ
    if env.get("AIOPS_MODE"):
        s["mode"] = env["AIOPS_MODE"].strip().lower()
    if env.get("AIOPS_PROM_URL"):
        s["prometheus_url"] = env["AIOPS_PROM_URL"].rstrip("/")
    if env.get("AIOPS_API_URL"):
        s["api_url"] = env["AIOPS_API_URL"].rstrip("/")
    s["api_token"] = env.get("AIOPS_API_TOKEN", "")
    ex = s.setdefault("executor", {})
    if env.get("AIOPS_DEMO_DIR"):
        ex["demo_dir"] = env["AIOPS_DEMO_DIR"]
    if env.get("AIOPS_COMPOSE_FILE"):
        ex["compose_file"] = env["AIOPS_COMPOSE_FILE"]
    if env.get("AIOPS_EXECUTOR_ENABLED"):
        ex["enabled"] = env["AIOPS_EXECUTOR_ENABLED"].strip().lower() in ("1", "true", "yes")
    lab = s.setdefault("lab", {})
    if not lab.get("flagd_file") and ex.get("demo_dir"):
        lab["flagd_file"] = str(Path(ex["demo_dir"]) / "src" / "flagd" / "demo.flagd.json")
    return s


@lru_cache(maxsize=1)
def registry() -> dict:
    return _yaml("registry.yaml")


@lru_cache(maxsize=1)
def scenarios() -> list[dict]:
    return _yaml("scenarios.yaml").get("scenarios", [])


def services() -> dict:
    return registry().get("services", {})


def container_of(service: str) -> str:
    return services().get(service, {}).get("container", service)


def reset_caches() -> None:
    settings.cache_clear()
    registry.cache_clear()
    scenarios.cache_clear()

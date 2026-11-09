"""Thin Prometheus HTTP client + metric discovery. Works with the OpenTelemetry demo's Prometheus."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests


class PromError(Exception):
    pass


class Prom:
    def __init__(self, base_url: str, timeout: float = 8.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            r = requests.get(f"{self.base}{path}", params=params, timeout=self.timeout)
            r.raise_for_status()
            body = r.json()
        except requests.RequestException as e:
            raise PromError(f"Cannot reach Prometheus at {self.base}: {e.__class__.__name__}") from e
        except ValueError as e:
            raise PromError("Prometheus returned a non-JSON response") from e
        if body.get("status") != "success":
            raise PromError(body.get("error", "Prometheus query failed"))
        return body["data"]

    def healthy(self) -> tuple[bool, str]:
        try:
            self._get("/api/v1/query", {"query": "vector(1)"})
            return True, "Prometheus reachable"
        except PromError as e:
            return False, str(e)

    def metric_names(self) -> list[str]:
        return list(self._get("/api/v1/label/__name__/values"))

    def query(self, q: str) -> list[dict]:
        return self._get("/api/v1/query", {"query": q}).get("result", [])

    def range_by(self, q: str, label: str, minutes: int, step: int = 60, end_ts: float | None = None) -> pd.DataFrame:
        """Run a range query and return a wide frame: index = time, columns = values of `label`.
        All queries of one refresh share `end_ts` (aligned to the step) so their timestamps line up exactly."""
        end_ts = end_ts if end_ts is not None else (time.time() // step) * step
        end = datetime.fromtimestamp(end_ts, tz=timezone.utc)
        start = end - timedelta(minutes=minutes)
        data = self._get("/api/v1/query_range", {
            "query": q, "start": start.timestamp(), "end": end.timestamp(), "step": step})
        cols: dict[str, pd.Series] = {}
        for item in data.get("result", []):
            key = item["metric"].get(label)
            if key is None:
                continue
            pts = [(datetime.fromtimestamp(float(t), tz=timezone.utc), float(v))
                   for t, v in item["values"] if v not in ("NaN", "+Inf", "-Inf")]
            if not pts:
                continue
            s = pd.Series({t: v for t, v in pts}, name=key)
            cols[key] = s if key not in cols else cols[key].add(s, fill_value=0)
        if not cols:
            return pd.DataFrame()
        df = pd.DataFrame(cols).sort_index()
        df.index = pd.DatetimeIndex(df.index).tz_convert(None)
        return df


# ----------------------------------------------------------------------------- discovery
_CALLS = ["traces_span_metrics_calls_total", "traces_spanmetrics_calls_total", "calls_total",
          "traces_span_metrics_calls"]
_BUCKET = ["traces_span_metrics_duration_milliseconds_bucket", "traces_span_metrics_duration_seconds_bucket",
           "traces_spanmetrics_latency_bucket", "traces_spanmetrics_duration_milliseconds_bucket"]
_disc_cache: dict = {}


def _first(names: set[str], candidates: list[str], pattern: str | None = None) -> str | None:
    for c in candidates:
        if c in names:
            return c
    if pattern:
        rx = re.compile(pattern)
        for n in sorted(names):
            if rx.search(n):
                return n
    return None


def discover(prom: Prom, force: bool = False) -> dict:
    """Find which metric names this Prometheus exposes (they differ between demo versions)."""
    key = prom.base
    hit = _disc_cache.get(key)
    if hit and not force and time.time() - hit["at"] < 300:
        return hit["d"]
    names = set(prom.metric_names())
    calls = _first(names, _CALLS, r"calls(_total)?$")
    bucket = _first(names, _BUCKET, r"(duration|latency).*_bucket$")
    cpu = _first(names, [], r"^container_cpu_utilization") or _first(names, [], r"^container_cpu_usage")
    mem = (_first(names, [], r"^container_memory_rss") or _first(names, [], r"^container_memory_usage_total")
           or _first(names, [], r"^container_memory_(usage|working_set)"))
    kafka_lag = _first(names, [], r"kafka.*lag")
    kind_filter = ""
    if calls:
        try:
            kinds = {r["metric"].get("span_kind") for r in prom.query(f"count by (span_kind) ({calls})")}
            if "SPAN_KIND_SERVER" in kinds:
                kind_filter = 'span_kind="SPAN_KIND_SERVER"'
        except PromError:
            pass
    d = {
        "calls": calls, "bucket": bucket, "cpu": cpu, "mem": mem, "kafka_lag": kafka_lag,
        "kind_filter": kind_filter,
        "latency_unit": "s" if bucket and "seconds" in bucket and "milli" not in bucket else "ms",
        "n_metrics": len(names),
    }
    _disc_cache[key] = {"at": time.time(), "d": d}
    return d

"""TEST DOUBLE ONLY. A tiny Prometheus-compatible HTTP server used by the automated tests.
It produces synthetic series so the analysis code can be tested without Docker. The application itself never
contains or generates data: in real use it reads the OpenTelemetry demo's Prometheus."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

SERVICES = ["frontend-proxy", "frontend", "cart", "checkout", "payment", "product-catalog", "email", "ad",
            "currency", "shipping", "quote", "recommendation", "image-provider"]
BASE_RPS = {s: 3.0 for s in SERVICES}
BASE_RPS.update({"frontend-proxy": 8.0, "frontend": 7.0, "product-catalog": 6.0, "currency": 5.0})
NAMES = ["traces_span_metrics_calls_total", "traces_span_metrics_duration_milliseconds_bucket",
         "container_cpu_utilization_ratio", "container_memory_rss_bytes", "up"]


def value(kind: str, svc: str, i: int, n: int) -> float:
    """i = index in the series, n = length. The last points carry the injected faults."""
    rng = np.random.RandomState((abs(hash(svc)) % 10000) + i)
    tail = n - i  # 1 = newest
    noise = rng.normal(0, 0.03)
    rps = BASE_RPS[svc] * (1 + noise)
    err, p95, cpu, mem = 0.003 + abs(noise) * 0.02, 40 * (1 + noise), 0.15 * (1 + noise), 150e6 * (1 + noise * 0.1)
    if svc == "cart" and tail <= 9:
        err, p95 = 0.35, 220
    if svc == "payment" and tail <= 8:
        rps = 0.02
    if svc == "ad" and tail <= 9:
        cpu, p95 = 0.95, 180
    if svc == "email" and tail <= 35:
        mem = 150e6 * (1 + (35 - tail) * 0.03)
    if svc == "frontend-proxy" and tail <= 8:
        pass
    return {"rps": rps / 60.0, "err": rps / 60.0 * err, "p95": p95, "cpu": cpu, "mem": mem}[kind]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/api/v1/label/__name__/values":
            return self._send({"status": "success", "data": NAMES})
        q = qs.get("query", "")
        if u.path == "/api/v1/query":
            if "span_kind" in q:
                return self._send({"status": "success", "data": {"result": [{"metric": {"span_kind": "SPAN_KIND_SERVER"}, "value": [0, "1"]}]}})
            return self._send({"status": "success", "data": {"result": [{"metric": {}, "value": [0, "1"]}]}})
        if u.path == "/api/v1/query_range":
            start, end, step = float(qs["start"]), float(qs["end"]), float(qs["step"])
            ts = np.arange(start, end + 1, step)
            n = len(ts)
            if "histogram_quantile" in q:
                kind, lab = "p95", "service_name"
            elif "status_code" in q:
                kind, lab = "err", "service_name"
            elif "container_cpu" in q:
                kind, lab = "cpu", "container_name"
            elif "container_memory" in q:
                kind, lab = "mem", "container_name"
            else:
                kind, lab = "rps", "service_name"
            res = [{"metric": {lab: s}, "values": [[float(t), str(value(kind, s, i, n))] for i, t in enumerate(ts)]}
                   for s in SERVICES]
            return self._send({"status": "success", "data": {"resultType": "matrix", "result": res}})
        self.send_response(404)
        self.end_headers()


def start(port: int = 0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"

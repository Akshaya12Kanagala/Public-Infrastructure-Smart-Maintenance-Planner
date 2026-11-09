# Frontend guide (Streamlit control room)

## What it covers (stakeholder requirement -> page)

| Requirement | Where it is |
|---|---|
| Anomaly detection for abnormal behaviour | **Asset Detail** (normal band + anomaly markers per metric), **Risk Ranking** (signals) |
| AI-driven prioritisation by severity, cost and public impact | **Risk Ranking** (Urgency = Severity x Downtime cost x User impact, with breakdown chart) |
| Automatic work-order generation with estimated repair requirements | **Work Orders** (effort, resources, approval, risk, steps, SLA, verification, rollback) |
| Folium / Mapbox visualisation | **Map & Dependencies** (Folium zone map; dependency graph with blast radius) |
| Observability (Prometheus) | Live data source for every page; **Guardrails & Settings > System status / Metric explorer** |
| Increase in proactive repairs | **Success Metrics** (proactive share) |
| Reduced response time for critical incidents | **Success Metrics** (manual baseline vs assisted) |
| RAG over the rulebook, citations | **AI Assistant**, **Rulebook** |
| Human in the loop, guardrails, audit | **Work Orders** approval, **Guardrails & Settings** (automation mode, kill switch, audit log) |
| Real environment, real incidents | **Scenario Lab** |

## Run

```bash
cd frontend
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
python -m pytest tests -q          # 20 tests, no Docker needed
```

## Two modes

| Mode | When | How it works |
|---|---|---|
| `local` (default) | Backend not built yet | The app reads Prometheus directly and runs a **preview engine** (`core/engine.py`): robust z-scores (median/MAD, threshold 3.5) per service against its own last 60 minutes, trend-to-breach estimate, severity, urgency, incidents, runbook match (TF-IDF over `knowledge/rulebook.md`), work-orders. |
| `api` | FastAPI + Scikit-learn services exist | Set `AIOPS_MODE=api`. Pages get ranking, incidents, work-orders, decisions and chat from the backend (`core/api.py`, contract in `API_CONTRACT.md`). Charts still read Prometheus directly. |

Nothing is generated: if Prometheus is unreachable or empty the pages show an explicit "No live data" state.

## Code map

```
app.py                 navigation, sidebar, theme
core/config.py         YAML + env settings
core/prom.py           Prometheus client + metric-name discovery
core/engine.py         preview analytics: severity, urgency, incidents
core/rulebook.py       parse rulebook.md, TF-IDF matching
core/workorders.py     work-order generation (effort/resources/steps come from the rulebook)
core/executor.py       allow-listed sandbox actions, rate limit, kill switch, audit
core/store.py          SQLite: incidents, work-orders, audit, scenario runs
core/metrics.py        success metrics from recorded events
core/service.py        facade used by pages (local vs api)
core/api.py            FastAPI client
views/*.py             the 11 pages
config/*.yaml          settings, service registry (business context), scenarios
knowledge/rulebook.md  the rulebook (sandbox edition)
tests/                 core + UI tests (a test double stands in for Prometheus)
```

## How the numbers are built

- **Severity (0..1)** = the worst of: error ratio (vs 25% = 1.0, only when above SLO or a statistical outlier), latency
  (1.5x to 6x normal), traffic spike (2x to 8x) or drop (below 30% of normal), CPU increase, steady memory growth
  (>25% in 30 min), and a predicted limit breach within 30 minutes.
- **Urgency** = 100 x severity x cost weight x impact (healthy = 0). Cost weight = cost/min relative to the most
  expensive service; impact is 0..1; both from `config/registry.yaml`.
- **Proactive** = the incident was opened while the service was still inside its error SLO.
- **Root-cause hint**: if a dependency is at least as unhealthy as its caller, the caller's incident points to it.

## Roles in the preview

`viewer` (read only), `engineer` (assign, run scenarios), `admin` (approve, execute, settings, kill switch).
In `api` mode the backend's JWT roles must be enforced server-side; the UI only hides controls.

## Known limits (be upfront with reviewers)

- The preview engine evaluates when the dashboard is open (about every 20 seconds), not as a background service. The
  production design runs scoring on a schedule in the backend.
- Metrics arrive about once a minute in the demo, so detection is minute-scale, not second-scale.
- Business costs, impact weights and zones in `registry.yaml` are assumptions until the stakeholder supplies figures.
- Folium uses OpenStreetMap tiles; Mapbox can be added later with a token.
- `api` mode is written to the contract but has not been run against the real backend yet.
- The remedy executor works with Docker Compose and feature flags only; scale-out belongs to the Kubernetes edition.

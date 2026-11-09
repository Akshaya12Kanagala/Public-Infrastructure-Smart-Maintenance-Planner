# Sandbox environment: a real system with real failures

The stakeholder asked for a **real environment**, not generated values. So the data in this project is never typed in
or randomly generated. Instead we run a real microservice system, put real load on it, and switch on real failure
modes. The dashboard only reads what that system reports.

```
 Load generator (real traffic)
        |
        v
 OpenTelemetry "Astronomy Shop"  (about 15 services in Docker: frontend, cart, checkout, payment, ...)
        |  real metrics, traces, logs
        v
 Prometheus :9090  <---------------  Streamlit control room :8501  (this project's frontend)
        ^                                   |
        |                                   | Scenario Lab / approved remedies (allow-listed only)
 Feature flags (flagd)  <-------------------+
   = real failure modes: flood, errors, CPU, memory leak, slow responses, unreachable dependency
```

The system is the open-source **OpenTelemetry Demo** (github.com/open-telemetry/opentelemetry-demo). It ships with a
load generator, Prometheus, a feature-flag UI and a set of built-in failure scenarios.

## 1. Where to run it

| Option | Good for | Facts to know |
|---|---|---|
| **Your own laptop with Docker Desktop** (recommended) | Everything | The demo documents about 6 GB RAM for the full app (about 3 GB in minimal mode) and about 14 GB of disk. 16 GB RAM laptop is comfortable. |
| **GitHub Codespaces** (no powerful laptop needed) | Team demos, weak laptops | Free personal accounts include 120 core-hours and 15 GB storage per month. A 4-core/16 GB codespace uses 4 core-hours per hour, so about 30 hours per month; stop the codespace when idle. A 2-core/8 GB machine fits only minimal mode. |
| **A small cloud VM** (4 vCPU, 16 GB) | Always-on demo for reviews | You pay for it unless you use free credits. |
| Browser labs (Play with Docker, Killercoda) | Trying single commands | Sessions are short (reported around 1 to 2 hours) and resources are small and shared: not suitable for this multi-service system. |

Limits above are as published at the time of writing; check the providers' pages before relying on them.

## 2. Start the sandbox (local machine or Codespaces terminal)

1. Install Docker (Docker Desktop on Windows/macOS; on Windows enable WSL2). Check: `docker compose version` (v2).
2. In the repository root run:
   ```bash
   ./frontend/scripts/start_sandbox.sh            # full demo
   # or, on small machines:
   ./frontend/scripts/start_sandbox.sh minimal    # no Kafka, about 3 GB RAM
   ```
   This clones the demo to `~/opentelemetry-demo` and runs `docker compose up` (equivalent to the demo's own
   documented command).
3. Check the containers: `cd ~/opentelemetry-demo && docker compose ps` (everything `running`).
4. Open: shop `http://localhost:8080/`, feature flags `http://localhost:8080/feature`, load generator
   `http://localhost:8080/loadgen/`, Prometheus `http://localhost:9090`.
5. **Wait 5 to 10 minutes.** The demo exports metrics about once a minute and the dashboard needs history to learn
   what "normal" looks like (it compares the last 5 minutes with the previous 60).
6. In Prometheus (Graph tab) run `traces_span_metrics_calls_total`. If you get series, the pipeline works. If the
   name differs in your demo version, use the dashboard's *Guardrails & Settings > Metric explorer*; it discovers names
   automatically.

### Codespaces specifics
1. On GitHub: repository > Code > Codespaces > "New with options" > machine type **4-core**. The included
   `.devcontainer/devcontainer.json` adds Docker and forwards ports 8080, 9090, 8501.
2. In the codespace terminal run step 2 above.
3. Start the frontend (section 3) in the same codespace; open the forwarded port 8501 from the Ports tab. Keep
   port visibility **private**.
4. Stop the codespace when you are done (Codespaces menu > Stop) so it does not use up the free hours.

## 3. Run the frontend

```bash
cd frontend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```
Edit `.env` on the machine that runs the sandbox:
```
AIOPS_PROM_URL=http://localhost:9090
AIOPS_DEMO_DIR=/home/<you>/opentelemetry-demo      # enables the Scenario Lab to switch failure flags
# AIOPS_EXECUTOR_ENABLED=true                       # only after your first dry run (see section 5)
```
Then:
```bash
python scripts/check_environment.py     # shows what was found and which scenarios exist in your demo version
streamlit run app.py                    # http://localhost:8501
```

## 4. Confirm the flag file is live (one-time check)

The Scenario Lab edits `src/flagd/demo.flagd.json` inside the demo folder. Check that this is the file your demo reads:
1. Open `http://localhost:8080/feature`, switch any flag on, then run
   `git -C ~/opentelemetry-demo diff --stat src/flagd/demo.flagd.json`.
   If the file shows a change, the Lab and the UI control the same thing.
2. If the file did **not** change, your demo version stores flags elsewhere. Use the Lab in logging mode: switch the
   flag in the Feature Flag UI and press **"I switched it on"** in the Lab so the timings are recorded.

## 5. Scenario playbook (real failure modes, real-world analogues)

Flag names are from the demo's `demo.flagd.json`. Analogues describe the *class* of incident; read each company's own
post-mortem for exact details before quoting them in a report.

| Scenario (flag = value) | What really happens in the system | Real-world class of incident | What a team does by hand | What this system does (rulebook) |
|---|---|---|---|---|
| Traffic flood (`loadGeneratorFloodHomepage` = on) | Load generator floods the storefront | Flash crowd or application-layer DoS | Notice slowness, find the source, add a rate limit | Detects request rate far above normal, matches RB-101, proposes stopping the source |
| Cart errors (`cartFailure` = 50%) | Half of cart calls fail | Faulty release or config push | Check dashboards, find the change, roll back | Error ratio above SLO, RB-102, proposes rolling the flag back (the "change") |
| Payment errors (`paymentFailure` = 50%) | Payment charges fail | Payment provider errors on the revenue path | Page the payments owner | RB-102 with highest cost weight, so top of the ranking |
| Payment unreachable (`paymentUnreachable` = on) | Payment service unavailable | Dependency unreachable / network partition | Trace the failing hop, restart or fail over | Payment traffic drop plus checkout errors, RB-103, hint "likely cause downstream: payment" |
| CPU exhaustion (`adHighCpu` = on) | Ad service burns CPU | Runaway computation (for example a regular expression that backtracks) | Find the hot container, restart | CPU far above own baseline, RB-104 |
| Memory leak (`emailMemoryLeak` = 100x) | Email service memory grows steadily | Leak ending in out-of-memory restarts | Notice only after a crash | Detects growth early (proactive), RB-105, restart as relief plus work-order for developers |
| Slow images (`imageSlowLoad` = 5sec) | Static content is slow | Degraded CDN or asset service | Users complain first | Latency anomaly without errors, RB-106 (no blind restart) |
| Queue falling behind (`kafkaQueueProblems` = 3sec) | Consumer lags behind (full demo only) | Message backlog | Find the stuck consumer | RB-107; needs the Kafka lag metric of your demo version (see Metric explorer) |

## 6. Run a proper experiment (for the success metrics)

For each scenario you want to report on:
1. **Manual baseline (3 runs):** Scenario Lab > mode "Manual baseline" > Start. Pretend the dashboard does not exist:
   find the cause with the shop's tools and fix it (press "Fix it by hand"). The Lab records the time to resolve.
2. **Assisted (3 runs):** mode "Assisted" > Start. Watch the Incident appear, open the Work-order, approve, verify.
3. Open **Success Metrics**. It shows detection delay, time to decision, and manual vs assisted resolution time, plus the
   share of proactive repairs. Three runs each is a minimum; more is better.

Executing remedies: the first time, leave `AIOPS_EXECUTOR_ENABLED` off and use "Approve (I run it myself)" so you can
see the exact command. Enable the executor only on the sandbox machine when you are comfortable.

## 7. What is real and what you must supply

| Real (measured) | Configuration you own (edit `config/registry.yaml`) |
|---|---|
| Request rate, errors, latency, CPU, memory, traffic drops | Downtime cost per minute per service and user-impact weight: **assumptions in the file**; ask the stakeholder for real figures |
| Failures (feature flags), their timing, detection and response times | Zone labels used on the map (the demo itself runs on one host) |
| Incidents, decisions and audit trail recorded by the app | Dependency list (matches the demo's architecture; verify for your version) |

## 8. Safety

- Everything here runs against **your own sandbox**. Never point the load generator or scenarios at anyone else's system.
- Do not expose ports 8501, 8080 or 9090 publicly. In Codespaces keep forwarded ports private.
- The executor can only run two allow-listed actions (restart one named service; switch one named flag off), is
  disabled by default, rate limited, and has a kill switch (Guardrails & Settings).

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard says "No live data" | Run `python scripts/check_environment.py`. Is Prometheus up on the URL in `.env`? Has the demo been running 5+ minutes? |
| Check script says "no span metrics" | Open Metric explorer, filter names by `span` or `calls`, and see what your version calls them. |
| Some services show "no data" | Minimal mode has fewer services, or container names differ. Set `container:` in `config/registry.yaml`. |
| CPU or memory not shown | Docker-stats metrics are not exposed in your version; detection still works from traffic, errors, latency. |
| Containers keep restarting or machine freezes | Not enough RAM: use minimal mode, close other apps, or use a 4-core Codespace. |
| Scenario started but nothing changes | Wait 1 to 3 minutes; confirm the flag shows as on in `/feature`; do the check in section 4. |
| Restart action fails | Set `AIOPS_COMPOSE_FILE` if you used the minimal compose file; check `docker compose ps` in the demo folder. |

# Smart Maintenance Planner: Streamlit control room

Frontend for the Public Infrastructure Smart Maintenance Planner. Shows live risk, incidents, auto-generated
work-orders with repair estimates, rulebook-grounded remedies, human approval, guardrails and success metrics, on top of
a **real sandbox system** (OpenTelemetry demo) with real failure scenarios.

Quick start:
1. Start the sandbox: `./scripts/start_sandbox.sh` (see `../docs/environment/ENVIRONMENT_SETUP.md`)
2. `pip install -r requirements.txt && cp .env.example .env`
3. `python scripts/check_environment.py`
4. `streamlit run app.py`

Docs: `../docs/frontend/FRONTEND_GUIDE.md`, `../docs/frontend/API_CONTRACT.md`, `../docs/GIT_PUSH_GUIDE.md`.

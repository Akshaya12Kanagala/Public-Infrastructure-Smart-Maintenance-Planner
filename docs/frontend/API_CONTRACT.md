# API contract expected by the frontend (`AIOPS_MODE=api`)

All endpoints are under `AIOPS_API_URL` (default `http://localhost:8000/api/v1`) with `Authorization: Bearer <JWT>`.
Roles (`viewer`, `engineer`, `admin`) must be enforced by the backend. Timestamps are ISO 8601 UTC.

| Method | Path | Used by | Role |
|---|---|---|---|
| POST | `/auth/login` | login | public |
| GET | `/risk/ranking` | most pages | viewer |
| GET | `/incidents` | Incidents | viewer |
| GET | `/work-orders` | Work Orders | viewer |
| POST | `/work-orders/{id}/approve` , `/reject` | Work Orders | admin |
| POST | `/chat` | AI Assistant | viewer |
| GET | `/audit-logs` | Guardrails & Settings | admin |

## GET /risk/ranking  ->  `{"items": [ ... ]}`
Required per item: `service`, `status` (`critical|high|medium|low|healthy|no data`), `severity` (0..1), `urgency` (0..100).
Optional (defaults are filled in by the frontend): `kind`, `zone`, `cost_norm`, `impact`, `cost_per_min`,
`exposure_per_min`, `rps`, `err_ratio` (0..1), `p95_ms`, `cpu` (0..1), `mem_mib`, `failed_per_min`, `eta_min`,
`signals` (list of strings), `symptom`, `hint`, `has_data` (bool).
```json
{"items": [{"service": "payment", "status": "critical", "severity": 0.78, "urgency": 70.4,
            "cost_norm": 1.0, "impact": 0.9, "rps": 3, "err_ratio": 0.0, "p95_ms": 41,
            "signals": ["traffic dropped to 1% of normal"], "has_data": true}]}
```

## GET /incidents  ->  `{"items": [ ... ]}`
`id`, `service`, `status` (`open|closed`), `level`, `severity`, `urgency`, `opened_at`, `closed_at`, `signals`
(string joined with `|`), `runbook_id`, `match_score`, `proactive` (0/1), `hint`.

## GET /work-orders  ->  `{"items": [ ... ]}`
```json
{"id": "WO-20261108-001", "incident_id": 1, "created_at": "...", "status": "proposed",
 "assignee": null, "decided_at": null, "executed_at": null, "verified_at": null,
 "execution": null, "verification": null,
 "payload": {
   "title": "[P1] payment: Dependency unreachable", "service": "payment", "priority": "P1", "level": "critical",
   "summary": "...", "evidence": ["..."], "hint": "",
   "runbook": {"id": "RB-103", "title": "...", "match_score": 0.77, "trusted": true},
   "steps": ["..."], "safety_limits": ["..."], "verify": ["..."], "rollback": ["..."],
   "escalate_if": ["..."], "mishap": ["..."],
   "estimate": {"effort_min": 15, "resources": "On-call engineer", "approval": "required", "risk": "Critical"},
   "plan": {"type": "restart", "target": "payment", "reason": "...", "command": "docker compose restart payment"},
   "sla_minutes": 15, "sla_due": "...",
   "snapshot": {"severity": 0.78, "urgency": 70.4}}}
```

## POST /work-orders/{id}/approve | reject
Body `{"reason": "text"}`. Response `{"ok": true, "output": "..."}`. Approve must record the actor, time and reason in
the audit log. Execution of remedies is the backend's responsibility (allow-list, dry-run, rate limit, rollback).

## POST /chat
Body `{"session_id": "...", "question": "..."}`. Response
`{"answer": "markdown", "citations": [{"type": "runbook", "title": "RB-104 / soft remedy (steps)", "score": 0.68}]}`.
If no source supports the answer, return a "no source" answer with an empty `citations` list.

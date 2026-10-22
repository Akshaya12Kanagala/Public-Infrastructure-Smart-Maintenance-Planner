# Public Infrastructure: Smart Maintenance Planner Soft Remediation Rulebook

**Version:** 0.1 (draft)
**Scope:** Docker / local Kubernetes sandbox only.
**Used by:** the AI agent (retrieved through RAG), engineers, and reviewers.

---

## 1. Global Rules (apply to every runbook)

1. **Allow-list only.** The agent may perform only these actions: `scale`, `restart`, `traffic-shift`, `rollback`, `rate-limit`.
2. **No destructive commands.** Never `delete`, `drop`, `rm`, `prune`, `kill -9`, or anything that removes data or resources.
3. **Named targets only.** Every command must name exactly one service from the service registry. Wildcards, "all", and command substitution such as `$(docker ps -q)` are blocked.
4. **Dry-run first** where the tool supports it (for example `--dry-run=server`), then execute.
5. **Step, don't jump.** Change one thing at a time, in small steps, and check metrics after each step.
6. **Verify after every action.** Compare error rate, p95 latency and CPU against the trigger values for at least 5 minutes.
7. **Auto-rollback.** If metrics get worse after an action, undo it and escalate.
8. **Human approval** is required when an action exceeds any limit in this document, or when a runbook is marked `Approval: required`.
9. **Rate limit on remedies.** Maximum 3 automatic actions per service per hour. After that, escalate to a human.
10. **Cite the runbook.** Every proposed work-order must reference the runbook ID it used.
11. **No source, no action.** If no runbook matches the situation, the agent must not guess. It escalates.

---

## 2. Runbook Entry Format

Every runbook follows this structure so it can be chunked and retrieved reliably:

```
## RB-XXX: Title
- Service scope / Severity / Approval
### Trigger
### Soft remedy (steps)
### Safety limits
### Verify
### Rollback
### Common mishap and fix
### Escalate if
```

---

## RB-001: High CPU or request overload, scale out

- **Service scope:** stateless services (for example `api-service`, `web-frontend`)
- **Severity:** High
- **Approval:** not required within limits

### Trigger
- CPU above 80% for 5 minutes, **or** p95 latency above the service SLO and request rate rising.
- Anomaly score from the ML service is above the critical threshold.

### Soft remedy (steps)
1. Check current state: `kubectl get deployment {service}`
2. Dry run: `kubectl scale deployment/{service} --replicas={current+2} --dry-run=server`
3. Apply: `kubectl scale deployment/{service} --replicas={current+2}`
4. Wait 2 minutes, check metrics, and repeat only if still above trigger.

### Safety limits
- Increase by **+2 replicas per step**.
- Never exceed `max_replicas` from the service registry (default **6**).
- Check database connections between steps (see RB-007).

### Verify
- CPU below 65% and p95 latency back under SLO for 5 minutes.
- No new 5xx errors.

### Rollback
- `kubectl scale deployment/{service} --replicas={original}` after load stays normal for 30 minutes.

### Common mishap and fix
- **Mishap:** `kubectl scale deployment/api-service --replicas=20` opened too many database connections and the database refused new ones.
- **Fix:** `kubectl scale deployment/api-service --replicas=4`, then review the connection pool settings.
- **Rule:** step up by +2 only and stay within `max_replicas`.

### Escalate if
- Limit reached and metrics are still above trigger.
- Database connection usage above 80%.

---

## RB-002: Unresponsive container, targeted restart

- **Service scope:** single container service (for example `auth-service`)
- **Severity:** High
- **Approval:** not required within limits

### Trigger
- Health check failing for 3 consecutive probes, or no response for 60 seconds.

### Soft remedy (steps)
1. Check health: `docker inspect --format '{{.State.Health.Status}}' {service}`
2. Read recent logs: `docker logs --tail 100 {service}`
3. Restart only this container: `docker restart {service}`

### Safety limits
- Restart **one named container** only.
- Maximum **2 automatic restarts per hour** per service.

### Verify
- Health status returns `healthy` within 2 minutes.
- Error rate returns to baseline.

### Rollback
- Not applicable (restart is non-destructive). If the service fails again, escalate.

### Common mishap and fix
- **Mishap:** `docker restart $(docker ps -q)` restarted every container and caused a wider outage.
- **Fix:** `docker restart auth-service`, targeting the named container only.
- **Rule:** wildcards and command substitution are blocked.

### Escalate if
- Second restart does not restore health.
- Logs show repeated crashes with the same error.

---

## RB-003: Errors after a deployment, roll back

- **Service scope:** any Kubernetes deployment (for example `payment-api`)
- **Severity:** Critical
- **Approval:** not required if the deploy happened in the last 15 minutes; otherwise required

### Trigger
- 5xx error rate above 5% **within 15 minutes after a rollout**.

### Soft remedy (steps)
1. Confirm a recent rollout: `kubectl rollout history deployment/{service}`
2. Roll back: `kubectl rollout undo deployment/{service}`
3. Watch progress: `kubectl rollout status deployment/{service}`

### Safety limits
- Roll back to the **previous revision only**.
- Do not roll back across a database migration (escalate instead).

### Verify
- Error rate below 1% for 10 minutes.
- All pods `Ready`.

### Rollback
- If the previous revision is also unhealthy, stop and escalate. Do not keep cycling revisions.

### Common mishap and fix
- **Mishap:** repeated restarts changed nothing because the new version itself was faulty.
- **Fix:** `kubectl rollout undo deployment/payment-api`.
- **Rule:** if errors start within 15 minutes of a deploy, prefer rollback over restart.

### Escalate if
- The release included a schema migration.
- The rollback does not reduce errors.

---

## RB-004: Memory leak and restart loop

- **Service scope:** any deployment (for example `report-service`)
- **Severity:** Medium to High
- **Approval:** required after the first automatic restart

### Trigger
- Pods show `OOMKilled` or `CrashLoopBackOff`, or memory rises steadily without recovering.

### Soft remedy (steps)
1. Inspect: `kubectl describe pod {pod}` and `kubectl top pods -l app={service}`
2. Temporary relief: `kubectl rollout restart deployment/{service}`
3. Attach the memory trend graph to the work-order for the development team.

### Safety limits
- Maximum **2 automatic restarts per hour**.
- Do not raise memory limits automatically.

### Verify
- Memory returns to baseline after restart and no new `OOMKilled` events for 30 minutes.

### Rollback
- Not applicable. If the leak returns quickly, consider RB-003 (a recent release may be the cause).

### Common mishap and fix
- **Mishap:** repeated restarts hid the leak and it was never fixed.
- **Fix:** restart only as temporary relief, always create a work-order with the memory trend and cite the pod events.
- **Rule:** automatic restarts stop after 2 per hour.

### Escalate if
- Leak recurs within 30 minutes of a restart.

---

## RB-005: Traffic shift away from an unhealthy backend

- **Service scope:** services behind an nginx load balancer
- **Severity:** High
- **Approval:** required for shifts above 50%

### Trigger
- One backend has error rate or latency far above its peers while others are healthy.

### Soft remedy (steps)
1. Edit the upstream weights (for example move the unhealthy backend to weight 1).
2. **Validate first:** `nginx -t`
3. Apply only if validation passes: `nginx -s reload`
4. Shift gradually: 80/20, check, then 50/50 if needed.

### Safety limits
- Never remove the last healthy backend from the pool.
- Always keep a copy of the previous config file.

### Verify
- Error rate on the shifted traffic falls; overall success rate recovers within 5 minutes.

### Rollback
- Restore the previous config file, then `nginx -t` and `nginx -s reload`.

### Common mishap and fix
- **Mishap:** a typo in the upstream config was reloaded without validation, breaking routing or sending all traffic to the unhealthy server.
- **Fix:** restore the previous config, run `nginx -t`, then reload.
- **Rule:** always run `nginx -t` before `nginx -s reload`.

### Escalate if
- Validation fails twice.
- All backends are unhealthy.

---

## RB-006: Traffic spike or suspected flood, rate limit

- **Service scope:** public endpoints (for example `/login`, `/api`)
- **Severity:** High
- **Approval:** required if the limit would affect more than one endpoint

### Trigger
- Request rate more than 5 times baseline in 5 minutes, with a rise in 429/5xx errors or many requests from few sources.

### Soft remedy (steps)
1. Scale out within RB-001 limits.
2. Enable or tighten an nginx `limit_req` rule on the affected endpoint only.
3. Validate and reload: `nginx -t`, then `nginx -s reload`.

### Safety limits
- Apply limits to **one endpoint at a time**.
- Start with a generous limit and tighten in steps.
- Do not block IP ranges automatically; propose it as a work-order for human approval.

### Verify
- Backend latency back under SLO; legitimate traffic still succeeds.

### Rollback
- Restore the previous nginx config when request rate returns to baseline for 30 minutes.

### Common mishap and fix
- **Mishap:** a limit set too tight blocked real users during a legitimate sales spike.
- **Fix:** relax the limit, review the traffic source breakdown before tightening again.
- **Rule:** distinguish a flash crowd from an attack before limiting.

### Escalate if
- Traffic appears malicious and persistent (route to security team).

---

## RB-007: Database connection exhaustion

- **Service scope:** services using PostgreSQL
- **Severity:** Critical
- **Approval:** required

### Trigger
- "too many connections" errors, or connection usage above 85% of the maximum.

### Soft remedy (steps)
1. Check usage: `SELECT count(*) FROM pg_stat_activity;`
2. **Stop scaling out** app services (do not apply RB-001).
3. Scale **down** the services that hold the most connections by one step.
4. Propose a connection pool (for example PgBouncer) change as a work-order.

### Safety limits
- Never terminate database sessions automatically.
- Never change the database `max_connections` automatically.

### Verify
- Connection usage below 70% and error messages cleared.

### Rollback
- Restore the previous replica count after a pool fix is in place.

### Common mishap and fix
- **Mishap:** scaling out the app to fix latency multiplied connections and made the outage worse.
- **Fix:** scale the app back down and fix pooling first.
- **Rule:** check database connections before every scale-out.

### Escalate if
- Usage stays above 85% after scale-down.

---

## Appendix: Quick Reference

| Situation | First choice | Runbook |
|---|---|---|
| High CPU / latency rising | Scale out in +2 steps | RB-001 |
| Container unresponsive | Restart that container | RB-002 |
| Errors right after deploy | Roll back | RB-003 |
| Memory leak / OOM | Restart as relief + work-order | RB-004 |
| One backend unhealthy | Gradual traffic shift | RB-005 |
| Request flood | Rate limit one endpoint | RB-006 |
| DB connections exhausted | Scale down app, fix pooling | RB-007 |

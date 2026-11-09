# Remediation Rulebook: Docker Compose sandbox edition

**Version:** 0.2 (draft, for the OpenTelemetry-demo sandbox)
**Scope:** Docker Compose sandbox only. Never run these against production or a real cloud account.
**Note:** scale-out is not available in this sandbox (the demo containers have fixed names and ports). The Kubernetes edition of the rulebook keeps the scale and rollout runbooks; this edition uses restart, feature-flag rollback and escalation.

## Global Rules

1. **Allow-list only.** Executable actions are `restart` and `flag_off` (feature-flag rollback). Everything else is a manual step.
2. **Named targets only.** One service per action, taken from the service registry. No wildcards, no "all", no command substitution.
3. **Dry-run first.** Show the exact command before running it.
4. **Verify after every action.** Compare error ratio, latency, CPU and memory with the values at detection for at least 3 minutes.
5. **Rate limit.** At most 3 automatic or approved actions per service per hour. After that, escalate to a human.
6. **Human approval** is required unless the runbook says "not required within limits".
7. **No source, no action.** If no runbook matches, the system escalates instead of guessing.
8. **Rollback.** A flag rollback is undone by restoring the previous variant. A restart cannot be undone; if it does not help, escalate.

---

## RB-101: Traffic flood or request surge
- **Keywords:** traffic flood surge spike request rate rps abuse ddos flash crowd overload
- **Service scope:** frontend-proxy, frontend
- **Severity:** High
- **Approval:** required
- **Executable action:** flag_off
- **Fallback action:** none
- **Estimated effort:** 10 minutes
- **Resources:** On-call engineer; edge or rate-limit configuration access

### Trigger
- Request rate more than 3 times its baseline, with rising latency or CPU on the front tier.

### Soft remedy (steps)
1. Confirm the surge source: open the load generator UI (http://localhost:8080/loadgen/) or the access logs.
2. Stop the abusive or accidental source. In the sandbox this is the flood flag; in production it is a rate limit or block at the edge.
3. If latency stays high after the source is stopped, restart only the affected front service: `docker compose restart frontend`.

### Safety limits
- Limit one endpoint or one source at a time.
- Never block a whole network range automatically; propose it as a work-order.

### Verify
- Request rate back within 1.5 times baseline and latency back to baseline for 5 minutes.

### Rollback
- Restore the previous flag variant if legitimate users are affected.

### Common mishap and fix
- **Mishap:** a limit set too tight blocked real users during a legitimate sales spike.
- **Fix:** relax the limit and look at the traffic source before tightening again.
- **Rule:** tell a flash crowd from an attack before limiting.

### Escalate if
- Traffic looks malicious and persists after the source is stopped (security team).

---

## RB-102: Dependency failing after a change
- **Keywords:** errors error rate failures failing dependency release deploy change regression cart payment product catalog
- **Service scope:** cart, payment, product-catalog, ad, checkout, frontend
- **Severity:** Critical
- **Approval:** required
- **Executable action:** flag_off
- **Fallback action:** restart
- **Estimated effort:** 15 minutes
- **Resources:** On-call engineer; owner of the changed service

### Trigger
- Error ratio above 2% (the SLO) on a service, especially soon after a release or configuration change.

### Soft remedy (steps)
1. Find the recent change: list feature flags that are not at their default variant (http://localhost:8080/feature).
2. Roll back the change: switch the responsible flag back to `off`. This is the fast, safe rollback used by many companies.
3. If no recent change is found, restart only the failing service: `docker compose restart <service>`.
4. Check the logs of the failing service: `docker compose logs --tail 100 <service>`.

### Safety limits
- Roll back the one flag that matches the failing service; never reset all flags.
- At most one restart per service per 10 minutes.

### Verify
- Error ratio below 1% for 5 minutes on the failing service and on the services that call it.

### Rollback
- Restore the previous flag variant. If errors return, escalate; do not keep toggling.

### Common mishap and fix
- **Mishap:** repeated restarts change nothing because the change itself is faulty.
- **Fix:** roll the change back instead of restarting.
- **Rule:** if errors start right after a change, prefer rollback over restart.

### Escalate if
- Rollback does not reduce errors.
- The cause is in a dependency further down the chain (check the dependency graph).

---

## RB-103: Dependency unreachable
- **Keywords:** unreachable unavailable down outage no traffic connection refused timeout dependency payment
- **Service scope:** payment, checkout
- **Severity:** Critical
- **Approval:** required
- **Executable action:** flag_off
- **Fallback action:** restart
- **Estimated effort:** 15 minutes
- **Resources:** On-call engineer; network or platform owner

### Trigger
- Traffic to a service drops sharply while the services that call it show errors or timeouts.

### Soft remedy (steps)
1. Check the container: `docker compose ps <service>` and `docker compose logs --tail 100 <service>`.
2. If a flag or change made the service unreachable, roll it back (flag to `off`).
3. Otherwise restart only that service: `docker compose restart <service>`.
4. Protect callers: confirm they fail fast instead of piling up retries.

### Safety limits
- One service at a time; restart at most once in 10 minutes.

### Verify
- Traffic to the service returns to baseline and caller errors fall below 1%.

### Rollback
- Not applicable to a restart; for a flag rollback restore the previous variant.

### Common mishap and fix
- **Mishap:** callers retry without limits and turn a short outage into a retry storm.
- **Fix:** cap retries and use back-off; restart only the unreachable service.
- **Rule:** recover the dependency first, then watch the callers.

### Escalate if
- The service stays unreachable after one restart (possible network or platform issue).

---

## RB-104: CPU saturation
- **Keywords:** cpu saturation high cpu load processor busy runaway computation throttling
- **Service scope:** ad, recommendation, frontend, any application service
- **Severity:** High
- **Approval:** not required within limits
- **Executable action:** flag_off
- **Fallback action:** restart
- **Estimated effort:** 10 minutes
- **Resources:** On-call engineer

### Trigger
- Container CPU far above its baseline and latency of that service rising.

### Soft remedy (steps)
1. Check what changed: flags not at default for this service (http://localhost:8080/feature).
2. Roll back the responsible flag; if there is none, restart the container: `docker compose restart <service>`.
3. Open a work-order for the developers with the CPU graph attached.

### Safety limits
- At most 2 automatic restarts per hour per service.

### Verify
- CPU back near baseline and latency back under SLO for 5 minutes.

### Rollback
- Restore the previous flag variant if the rollback made things worse.

### Common mishap and fix
- **Mishap:** restarting repeatedly hides a runaway computation that returns after minutes.
- **Fix:** treat the restart as relief only, and file the work-order with the evidence.
- **Rule:** after 2 restarts in an hour, stop and escalate.

### Escalate if
- CPU returns to the high level within 15 minutes of the action.

---

## RB-105: Memory leak
- **Keywords:** memory leak growth rss oom out of memory growing steadily restart loop
- **Service scope:** email, any application service
- **Severity:** Medium
- **Approval:** required after the first restart
- **Executable action:** restart
- **Fallback action:** none
- **Estimated effort:** 20 minutes
- **Resources:** On-call engineer; developers of the leaking service

### Trigger
- Container memory rises steadily over 30 minutes or more without recovering.

### Soft remedy (steps)
1. Confirm the trend on the memory graph of the Asset Detail page.
2. Restart as temporary relief: `docker compose restart <service>`.
3. Attach the memory trend to a work-order for the developers.

### Safety limits
- At most 2 restarts per hour per service.
- Never raise memory limits automatically.

### Verify
- Memory back to baseline after the restart and not growing again for 15 minutes.

### Rollback
- Not applicable. If the leak returns quickly, look for a recent release or flag change (RB-102).

### Common mishap and fix
- **Mishap:** scheduled restarts hide the leak and it is never fixed.
- **Fix:** restart only as relief and always raise the work-order with the memory trend.
- **Rule:** the restart does not close the work-order; the fix does.

### Escalate if
- Memory grows again within 30 minutes of a restart.

---

## RB-106: Latency degradation without errors
- **Keywords:** latency slow response degraded slowness p95 slow images lock contention shipping delay
- **Service scope:** frontend, image-provider, shipping, product-catalog
- **Severity:** Medium
- **Approval:** required
- **Executable action:** flag_off
- **Fallback action:** none
- **Estimated effort:** 15 minutes
- **Resources:** On-call engineer

### Trigger
- p95 latency several times above baseline while the error ratio is still low.

### Soft remedy (steps)
1. Find the slow hop in the traces (http://localhost:8080/jaeger/ui/).
2. Roll back any recent change or flag that slows that service.
3. If the slowness comes from a dependency, follow the runbook of that dependency.

### Safety limits
- Do not restart a service that is only slow; a restart adds load and cold caches.

### Verify
- p95 latency back within 1.5 times baseline for 10 minutes.

### Rollback
- Restore the previous flag variant if latency gets worse.

### Common mishap and fix
- **Mishap:** restarting a slow service during peak traffic made the slowdown an outage.
- **Fix:** find the slow dependency first and fix that.
- **Rule:** slow but healthy services are not restarted automatically.

### Escalate if
- No recent change explains the slowdown.

---

## RB-107: Queue consumer falling behind
- **Keywords:** queue backlog lag consumer kafka orders fraud accounting falling behind throttled
- **Service scope:** fraud-detection, accounting, kafka
- **Severity:** Medium
- **Approval:** required
- **Executable action:** flag_off
- **Fallback action:** restart
- **Estimated effort:** 20 minutes
- **Resources:** On-call engineer; owner of the consumer service

### Trigger
- Consumer lag climbing while producers keep sending (needs the Kafka lag metric of your demo version).

### Soft remedy (steps)
1. Check whether the consumer is alive: `docker compose ps fraud-detection` and its logs.
2. Roll back any flag that throttles or stops the consumer.
3. If the consumer is stuck, restart only that consumer: `docker compose restart fraud-detection`.

### Safety limits
- Never delete or reset topics or consumer groups.

### Verify
- Lag stops growing and starts to fall within 10 minutes.

### Rollback
- Restore the previous flag variant if the consumer misbehaves.

### Common mishap and fix
- **Mishap:** resetting offsets to clear the backlog dropped orders.
- **Fix:** let the consumer catch up, or scale consumers in the Kubernetes edition.
- **Rule:** never reset offsets or delete data to fix lag.

### Escalate if
- Lag keeps growing after the consumer is healthy.

---

## RB-108: No matching runbook (escalation)
- **Keywords:** unknown unclassified other anomaly unexplained
- **Service scope:** any
- **Severity:** Medium
- **Approval:** required
- **Executable action:** none
- **Fallback action:** none
- **Estimated effort:** 30 minutes
- **Resources:** On-call engineer

### Trigger
- An anomaly with no matching runbook.

### Soft remedy (steps)
1. Do not act automatically. Attach the signals and graphs to a work-order.
2. Assign an engineer and review the traces and logs of the service.

### Safety limits
- No automatic action.

### Verify
- A human confirms the cause and either closes the work-order or writes a new runbook.

### Rollback
- Not applicable.

### Common mishap and fix
- **Mishap:** guessing a fix for an unknown problem made it worse.
- **Fix:** escalate and learn; add a runbook afterwards.
- **Rule:** no source, no action.

### Escalate if
- Always.

---

## Lessons from public post-mortems (why these rules exist)

- **Wrong command scope (storage provider outage, February 2017):** a maintenance command was entered with the wrong scope and removed more servers than intended. Rule: named targets only, dry-run first, minimum capacity floors.
- **Right command, wrong machine (code-hosting provider, January 2017):** while repairing replication, a data directory was deleted on the wrong database host. Rule: confirm the host and the role before any destructive step; destructive commands are never in the allow-list.
- **Runaway CPU (CDN provider, July 2019):** a new rule with a regular expression that backtracked heavily exhausted CPU worldwide. Rule: a change that raises CPU is rolled back first, and releases go out in stages.
- **Configuration change cut the network (social platform, October 2021):** a maintenance configuration change withdrew the routes that connected the data centres. Rule: validate every change before applying and keep an out-of-band way back in.
- **Short network partition, long recovery (code-hosting provider, October 2018):** about 43 seconds of lost connectivity led to inconsistent database topology and a day of degraded service. Rule: do not fail over repeatedly; verify state before each step.
- **Faulty content update (security vendor, July 2024):** one bad update crashed a very large number of machines. Rule: staged rollouts and an immediate rollback path.

Read the companies' own post-mortems for the exact details before quoting them in a report.

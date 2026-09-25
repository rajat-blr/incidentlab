# Failure modes and recovery

| Failure | Visible outcome | Recovery |
| --- | --- | --- |
| Fixture does not reproduce | Run fails before diagnosis | Reset the fixture, inspect service logs, and start a new idempotency key |
| Worker stops | Temporal retains the run; UI remains at the last durable state | Restart `worker`; stable effect keys prevent duplicate writes |
| Gemini timeout or invalid schema | Run fails closed with a categorized rejection event | Retry with a new run after provider recovery; inspect audit history |
| Empty or delayed telemetry | Explicit `gap` evidence; diagnosis cannot cite it as support | Check Collector/backends and repeat after telemetry is available |
| Baseline does not fail | Verification is `INCONCLUSIVE`, never `PASS` | Repair the scenario setup and rerun verification |
| Candidate still reproduces incident | Verification is `FAIL` | Reject the candidate and review raw check logs |
| Sandbox timeout/output limit | Verification is `INCONCLUSIVE` with preserved bounded log | Fix infrastructure or reduce the deterministic workload |
| Verifier service stops | Run remains visibly in `VERIFYING`; no outcome is inferred | Restart `verifier`; it resumes unverified candidates and re-signals persisted results idempotently |
| Duplicate API request | Existing run is returned | Reuse the original run ID |
| Invalid/over-privileged GitHub installation | Webhook returns 403; no write occurs | Correct App permissions and reinstall |
| Draft-PR retry | Existing draft is returned from the deterministic head branch | Continue review in the same PR |

Never interpret a missing check, provider error, or infrastructure interruption as
proof that a repair works.

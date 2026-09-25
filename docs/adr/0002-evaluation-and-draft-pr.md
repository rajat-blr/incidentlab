# ADR 0002: Evaluation oracle and optional draft PRs

**Status:** Accepted, 2026-09-25

## Decision

Use a deterministic offline pipeline oracle for release regression evaluation and
report live-model results separately. Add GitHub only as an explicit CLI-driven,
draft-only integration after local verification succeeds.

## Rationale

An offline oracle makes CI repeatable and free of provider quota, while the two
weaker baselines keep the metrics comparative. It cannot measure live model quality,
so reports state that limitation and retain model provenance for separate trials.

GitHub writes use a deterministic branch, query for an existing PR before writing,
and require `metadata:read`, `contents:write`, and `pull_requests:write`. The adapter
does not expose merge, deploy, workflow, or administration operations. A second
human approval is recorded independently from repair generation.

## Consequences

The local product remains complete without GitHub credentials. Creating a draft PR
requires deliberate operator configuration and invocation. Multiple file updates
may create multiple commits, but retries converge on one branch and one draft PR.

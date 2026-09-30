# IncidentLab

IncidentLab is an evidence-backed incident investigation and repair-verification
system. It reproduces a failure, gathers attributable telemetry and source
context, produces a structured diagnosis, and verifies a proposed repair inside
an isolated sandbox.

The project explores a practical question: **how can an AI-assisted incident
workflow remain useful without allowing the model to become the source of
truth?**

IncidentLab keeps collection, approval, policy enforcement, and verification
outside the model. The model can explain evidence and propose a bounded change;
deterministic controls decide what is accepted.

## Live demo

### [Launch IncidentLab →](https://incidentlab-flax.vercel.app/runs)

The deployed experience runs entirely from curated saved investigation data. It
does not require an account, backend service, or API key.

## What the demo shows

The browser-only demo contains seven investigation histories with successful,
failed, inconclusive, closed, and cancelled outcomes. It also lets a visitor
start a guided replay for either supported incident:

- **Pool exhaustion** — rejected checkout requests leak database connections
  until a valid request times out.
- **Inventory underflow** — an oversized checkout bypasses the stock guard and
  commits a negative inventory quantity.

A guided replay moves through reproduction, evidence collection, diagnosis,
human approval, repair generation, and verification using curated saved data.

## Investigation pipeline

```text
Reproduce incident
       │
       ▼
Collect traces, metrics, logs, and pinned source
       │
       ▼
Generate evidence-cited diagnosis
       │
       ▼
Human approval checkpoint
       │
       ▼
Generate bounded repair candidate
       │
       ▼
Apply deterministic repair policy
       │
       ▼
Verify in an isolated Docker sandbox
       │
       ▼
Persist facts, audit history, and report
```

The final result is derived from fixed verification checks—not from a model
claiming that its own repair worked.

## System architecture

```text
Sample checkout service
   ├── traces ─── Jaeger ──────┐
   ├── metrics ─ Prometheus ───┼── Evidence collector
   └── logs ──── Loki ─────────┘          │
                                          ▼
React console ─ FastAPI ─ PostgreSQL ─ Temporal workflow
                                          │
                                   OpenAI adapters
                                          │
                                   Repair policy
                                          │
                                          ▼
                           Trusted verifier ─ Docker sandbox
```

The API and model worker never receive the Docker socket. A separate trusted
verifier owns sandbox execution and records check results before the workflow
derives its terminal state.

## Core design choices

### Evidence before explanation

Every diagnosis citation must resolve to stored evidence. Missing telemetry is
recorded as an explicit gap rather than silently ignored.

### Human-controlled repair generation

Diagnosis is separated from repair. A reviewer must explicitly approve repair
generation, and rejection closes the investigation without producing a patch.

### Fail-closed repair policy

Model output is converted into a deterministic unified diff against a pinned
commit. Path, size, secret, syntax, and clean-application checks run before a
candidate can reach verification.

### Independent verification

Candidates run in a network-disabled, non-root container with resource limits.
Baseline reproduction, compilation, static analysis, unit tests, integration
tests, and repeated incident replay are stored as hash-verified facts.

### Durable and inspectable execution

Temporal provides retry-safe orchestration. PostgreSQL stores investigation
state, evidence, model usage, decisions, verification results, and the audit
trail exposed by the review console.

## Technology

| Area | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, TanStack Query |
| API | FastAPI, SQLAlchemy, Alembic |
| Workflow | Temporal |
| Storage | PostgreSQL |
| Observability | OpenTelemetry, Jaeger, Prometheus, Loki |
| Model integration | OpenAI Structured Outputs |
| Verification | Docker sandbox with fixed checks |
| Local environment | Docker Compose, uv |

## Repository map

```text
incidentlab/       API, workflows, persistence, evidence, policy, and verification
frontend/          React review console, guided replay, and saved demo data
sample_service/    Fault-injected checkout service and replay utilities
scenarios/         Public scenario definitions and private evaluation truth
telemetry/         Collector, Prometheus, and Loki configuration
migrations/        Database migrations
scripts/           Evaluation and operational utilities
tests/             Backend test suite
docs/              Architecture, threat model, sandbox, and evaluation notes
```

## Further reading

- [Architecture](docs/architecture.md)
- [Threat model](docs/threat-model.md)
- [Sandbox boundary](docs/sandbox.md)
- [Evaluation methodology](docs/evaluation.md)
- [Failure modes](docs/failure-modes.md)
- [Container releases](docs/container-release.md)

## Scope

IncidentLab is a portfolio and educational system built around controlled,
deterministic scenarios. It is not a production incident-response platform, and
the sandbox should not be treated as a hardened boundary for arbitrary untrusted
repositories.

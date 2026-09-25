# IncidentLab

IncidentLab is a local, evidence-backed incident diagnosis and repair-verification
lab. It reproduces a deterministic service failure, collects attributable
telemetry and repository evidence, asks Gemini for structured root-cause
hypotheses, and enforces a human approval gate before repair work proceeds.

> [!IMPORTANT]
> IncidentLab is an educational development project, not a production incident
> response system. It does not merge code or deploy changes.

Steps 1–8 of the [build plan](incidentlab-prd-and-build-plan.md) are complete.
Repair generation and workflow-integrated candidate verification remain roadmap work.

## What works today

- Deterministic database connection-pool exhaustion scenario.
- Durable, idempotent Temporal workflow with retries, cancellation, and approval.
- OpenTelemetry traces, Prometheus metrics, and Loki logs collected through an
  OpenTelemetry Collector.
- Immutable raw evidence artifacts with SHA-256 verification and normalized
  evidence records.
- Gemini diagnosis with structured output, validated citations, bounded follow-up
  lookups, secret redaction, and prompt-injection defenses.
- PostgreSQL persistence, Alembic migrations, audit events, model-usage records,
  and REST endpoints for runs, evidence, hypotheses, approval, and cancellation.
- Repeatable acceptance checks for workflow durability, evidence integrity, and
  live diagnosis.
- An independent Docker sandbox for manually supplied patches, with pinned inputs,
  fixed checks, resource limits, hashed artifacts, and hostile-code containment.

## Architecture

```text
Checkout gateway -> Inventory service -> SQLite fixture
        |                  |
        +---- OpenTelemetry traces, metrics, and logs ----+
                                                          v
                                              OTel Collector
                                               /     |     \
                                          Jaeger Prometheus Loki
                                               \     |     /
                                                Evidence collector
                                                        |
FastAPI -> PostgreSQL <- Temporal workflow/worker -> Gemini adapter
                                                        |
                                           Validated hypotheses + audit trail

Manual patch -> Host-side sandbox runner -> Constrained verification container
```

The sample inventory service owns a two-connection pool. In `pool_leak` mode,
failed checkout requests leak connections; a later valid request receives HTTP
503. With the fault disabled, connections are returned and the same valid
request succeeds.

## Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Docker Desktop with Compose
- A Gemini Developer API key for the live diagnosis check

## Quick start

1. Install the locked Python environment:

   ```sh
   uv sync --frozen
   ```

2. Create a local environment file and add a newly generated Gemini key:

   ```sh
   cp .env.example .env
   ```

   ```dotenv
   GEMINI_API_KEY=your-key
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

   `.env` is ignored by Git. Never commit or paste an active API key into an
   issue, log, or pull request.

3. Start the stack:

   ```sh
   docker compose up -d --build --wait
   ```

4. Confirm the API is ready:

   ```sh
   curl http://127.0.0.1:8000/ready
   ```

5. Run the acceptance checks:

   ```sh
   .venv/bin/python -m sample_service.telemetry_check
   .venv/bin/python -m sample_service.demo --trials 20
   .venv/bin/python scripts/step5_restart_check.py
   .venv/bin/python scripts/step6_evidence_check.py
   .venv/bin/python scripts/step7_diagnosis_check.py
   .venv/bin/python scripts/step8_sandbox_check.py
   ```

The Step 7 check makes a live Gemini request and rejects the repair at the human
approval gate, so placeholder repair generation does not continue.

## Development checks

```sh
.venv/bin/ruff check incidentlab sample_service tests migrations scripts
.venv/bin/ruff format --check incidentlab sample_service tests migrations scripts
TEST_DATABASE_ADMIN_URL=postgresql://incidentlab:incidentlab-local@127.0.0.1:55432/postgres \
.venv/bin/python -m unittest discover -s tests -v
```

The migration test creates and removes a temporary PostgreSQL database. The
Compose PostgreSQL service must be running.

## Local services

| Service | Address | Purpose |
| --- | --- | --- |
| IncidentLab API | `http://127.0.0.1:8000` | Runs, evidence, hypotheses, and approvals |
| Temporal UI | `http://127.0.0.1:8233` | Workflow history and activity attempts |
| Jaeger | `http://127.0.0.1:16686` | Distributed traces |
| Prometheus | `http://127.0.0.1:9090` | Pool and request metrics |
| PostgreSQL | `127.0.0.1:55432` | Durable application state |

Useful API routes include:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/scenarios` | List public scenario metadata |
| `POST` | `/runs` | Start or retrieve an idempotent run |
| `GET` | `/runs/{id}` | Read current run state |
| `GET` | `/runs/{id}/events` | Read the audit trail |
| `GET` | `/runs/{id}/evidence` | Read normalized evidence |
| `GET` | `/runs/{id}/hypotheses` | Read validated diagnosis results |
| `POST` | `/runs/{id}/repair-approval` | Approve or reject repair generation |
| `POST` | `/runs/{id}/cancel` | Request durable cancellation |

## Trust boundaries

- Telemetry, repository content, and model output are treated as untrusted.
- Model-proposed tool calls are allowlisted, typed, evidence-kind-specific, and
  capped at two lookups.
- Every hypothesis citation must resolve to stored evidence; `gap` records cannot
  support a hypothesis.
- Raw artifacts are size-bounded and hash-checked before use.
- The model cannot supply shell commands or determine verification outcomes.
- Human approval is required before repair generation.
- Verification uses a read-only, network-disabled, non-root container without the
  Docker socket or private evaluation inputs.

See [ADR 0001](docs/adr/0001-first-vertical-slice.md) for the initial scope and
security decisions, and [telemetry/queries.md](telemetry/queries.md) for the
bounded incident queries. The [sandbox boundary](docs/sandbox.md) documents the
implemented isolation controls and their limitations.

## Project layout

```text
incidentlab/       API, contracts, persistence, evidence, model, and workflow code
sample_service/    Fault-injected checkout fixture and replay tools
scenarios/         Public scenario contract and private evaluation truth
telemetry/         Collector, Prometheus, Loki, and query configuration
migrations/        Alembic database migrations
scripts/           Repeatable acceptance checks
tests/             Contract, migration, evidence, diagnosis, and fixture tests
docs/adr/           Architecture decision records
```

## Roadmap

The next milestone is Step 9: connect an approved diagnosis to bounded repair
generation and deterministic patch policy, then pass eligible candidates to the
independent verifier. The remaining sequence is tracked in the
[PRD and build plan](incidentlab-prd-and-build-plan.md).

Stop the local stack without deleting its volumes:

```sh
docker compose down
```

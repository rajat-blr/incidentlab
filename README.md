# IncidentLab

IncidentLab is a local, evidence-backed incident diagnosis and repair-verification
lab. It reproduces a deterministic service failure, collects attributable
telemetry and repository evidence, asks Gemini for structured root-cause
hypotheses, and enforces a human approval gate before repair work proceeds.

> [!IMPORTANT]
> IncidentLab is an educational development project, not a production incident
> response system. Its optional GitHub integration creates draft PRs only; it cannot
> mark them ready, merge code, or deploy changes.

Steps 1–14 of the [build plan](incidentlab-prd-and-build-plan.md) are complete.

## What works today

- Deterministic database connection-pool exhaustion and inventory-underflow scenarios.
- Durable, idempotent Temporal workflow with retries, cancellation, and approval.
- OpenTelemetry traces, Prometheus metrics, and Loki logs collected through an
  OpenTelemetry Collector.
- Immutable raw evidence artifacts with SHA-256 verification and normalized
  evidence records.
- Gemini diagnosis with structured output, validated citations, bounded follow-up
  lookups, secret redaction, and prompt-injection defenses.
- Approval-gated Gemini repair generation with bounded line replacements,
  deterministic unified diffs, and a fail-closed patch policy.
- Persisted baseline and post-patch checks with hash-addressed raw logs,
  fact-derived outcomes, explicit inconclusive handling, and deterministic ranking.
- A responsive React review console with live run status, evidence and diagnosis
  review, approval controls, safe diff rendering, verification logs, audit history,
  and deterministic Markdown report export.
- PostgreSQL persistence, Alembic migrations, audit events, model-usage records,
  and REST endpoints for runs, evidence, hypotheses, approval, and cancellation.
- Repeatable acceptance checks for workflow durability, evidence integrity, live
  diagnosis, repair policy, and candidate verification.
- An independent Docker sandbox for manually supplied patches, with pinned inputs,
  fixed checks, resource limits, hashed artifacts, and hostile-code containment.
- A versioned repeated-run evaluation harness with deterministic and uncited
  baselines, adversarial probes, CSV metrics, and explicit failure reports.
- An opt-in GitHub App boundary that validates webhook signatures and installation
  permissions and creates or reuses verified draft PRs idempotently.

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
FastAPI -> PostgreSQL <- Temporal workflow/worker -> Gemini adapters
                                                        |
                       Approved diagnosis -> patch policy -> candidate diff
                                                        |
                                                        v
Host-side sandbox runner ----------------> Constrained verification container
        |
        +-- explicit second approval --> Optional GitHub draft PR
```

The sample inventory service owns a two-connection pool. In `pool_leak` mode,
failed checkout requests leak connections; a later valid request receives HTTP
503. With the fault disabled, connections are returned and the same valid
request succeeds. In `inventory_underflow` mode, an oversized checkout bypasses
the stock guard and commits a negative quantity; the healthy control rejects it.

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

   Then open the review console at `http://127.0.0.1:5173`.

5. Run the acceptance checks:

   ```sh
   .venv/bin/python -m sample_service.telemetry_check
   .venv/bin/python -m sample_service.demo --trials 20
   .venv/bin/python scripts/step5_restart_check.py
   .venv/bin/python scripts/step6_evidence_check.py
   .venv/bin/python scripts/step7_diagnosis_check.py
   .venv/bin/python scripts/step8_sandbox_check.py
   .venv/bin/python scripts/step9_repair_check.py
   .venv/bin/python scripts/step10_verification_check.py
   .venv/bin/python scripts/evaluate.py --trials 5 --output evaluation-results/latest
   .venv/bin/python scripts/demo_release.py
   ```

The Step 7 and Step 9 checks make live Gemini requests. Step 9 records approval,
validates the generated candidate, and sends only a policy-accepted diff to the
independent sandbox verifier. Step 10 persists every verification log, derives
the terminal state from mandatory checks, and records deterministic ranking. The
evaluation and release demo are offline and do not require a model API key.

For an individual run already waiting in `VERIFYING`, invoke the trusted
host-side verifier with:

```sh
.venv/bin/python scripts/verify_run.py <run-id>
```

## Development checks

```sh
.venv/bin/ruff check incidentlab sample_service tests migrations scripts
.venv/bin/ruff format --check incidentlab sample_service tests migrations scripts
TEST_DATABASE_ADMIN_URL=postgresql://incidentlab:incidentlab-local@127.0.0.1:55432/postgres \
.venv/bin/python -m unittest discover -s tests -v
cd frontend && npm ci && npm run typecheck && npm test && npm run build
```

The migration test creates and removes a temporary PostgreSQL database. The
Compose PostgreSQL service must be running.

## Evaluation

The single release-evaluation command exports `report.json`, `metrics.csv`, and
`failures.json`. It compares IncidentLab with a deterministic keyword baseline and
an uncited one-shot baseline across both scenarios. See
[evaluation methodology](docs/evaluation.md) for metric definitions and limitations.

## Optional GitHub draft PR

The core product needs no GitHub credentials. To enable the optional integration,
create a private GitHub App from [the minimal manifest](docs/github-app.yml), expose
the signed webhook endpoint, and set the opt-in variables in `.env`. After a run has
a `PASS` candidate, record the separate approval and create or reuse its draft:

```sh
.venv/bin/python scripts/create_draft_pr.py RUN_ID --approved-by YOUR_NAME
```

The deterministic `incidentlab/run-RUN_ID` branch and remote PR lookup make retries
idempotent. The integration has no merge, deployment, workflow, or administration
operation.

## Local services

| Service | Address | Purpose |
| --- | --- | --- |
| IncidentLab review console | `http://127.0.0.1:5173` | Review runs, evidence, repairs, verification, and audit history |
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
| `GET` | `/runs` | List runs, optionally filtered by state |
| `GET` | `/runs/{id}` | Read current run state |
| `GET` | `/runs/{id}/events` | Read the audit trail |
| `GET` | `/runs/{id}/evidence` | Read normalized evidence |
| `GET` | `/runs/{id}/hypotheses` | Read validated diagnosis results |
| `GET` | `/runs/{id}/candidates` | Read policy-accepted repair candidates |
| `GET` | `/runs/{id}/verifications` | Read checks, outcomes, and candidate ranking |
| `GET` | `/runs/{id}/model-usage` | Read provider, token, latency, and recorded cost facts |
| `GET` | `/runs/{id}/report` | Download the deterministic JSON or Markdown report |
| `GET` | `/verification/artifacts/{id}` | Read a hash-verified raw check log |
| `POST` | `/runs/{id}/repair-approval` | Approve or reject repair generation |
| `POST` | `/runs/{id}/cancel` | Request durable cancellation |
| `POST` | `/integrations/github/webhook` | Validate signed GitHub App lifecycle events |

## Trust boundaries

- Telemetry, repository content, and model output are treated as untrusted.
- Model-proposed tool calls are allowlisted, typed, evidence-kind-specific, and
  capped at two lookups.
- Every hypothesis citation must resolve to stored evidence; `gap` records cannot
  support a hypothesis.
- Raw artifacts are size-bounded and hash-checked before use.
- The model cannot supply shell commands or determine verification outcomes.
- Human approval is required before repair generation.
- Model line replacements are converted to diffs against the exact pinned blob;
  allowlist, size, secret, syntax, and clean-apply checks run before persistence.
- Verification uses a read-only, network-disabled, non-root container without the
  Docker socket or private evaluation inputs.
- The API and model worker never receive the Docker socket; a separate trusted
  host command persists sandbox facts before signaling the durable workflow.
- GitHub writes require a separate recorded approval, a `PASS` verification, and
  an explicitly enabled installation token; only draft PRs can be created.

Start with the [architecture](docs/architecture.md), [threat model](docs/threat-model.md),
[failure modes](docs/failure-modes.md), and [release demo](docs/demo.md). The ADRs
record the [initial scope](docs/adr/0001-first-vertical-slice.md) and
[evaluation/GitHub tradeoffs](docs/adr/0002-evaluation-and-draft-pr.md). The
[sandbox boundary](docs/sandbox.md) documents isolation controls and limitations.

## Project layout

```text
incidentlab/       API, contracts, persistence, evidence, model, and workflow code
frontend/          React and TypeScript review console served by nginx
sample_service/    Fault-injected checkout fixture and replay tools
scenarios/         Public scenario contract and private evaluation truth
telemetry/         Collector, Prometheus, Loki, and query configuration
migrations/        Alembic database migrations
scripts/           Repeatable acceptance checks
evaluation-results/ Generated local evaluation output (ignored by Git)
tests/             Contract, migration, evidence, diagnosis, and fixture tests
docs/               Architecture, security, operations, evaluation, and ADRs
```

## Release status

The first-release definition of done is met. Future work is intentionally outside
the PRD: stronger isolation, arbitrary repository onboarding, additional providers,
and hosted multi-user operation.

Stop the local stack without deleting its volumes:

```sh
docker compose down
```

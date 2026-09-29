# IncidentLab

IncidentLab is an evidence-backed incident investigation and repair-verification
system. It reproduces deterministic failures in a sample distributed service,
collects telemetry and repository evidence, generates structured diagnoses with
OpenAI, and verifies proposed repairs inside an isolated Docker sandbox.

The repository includes two ways to explore the project:

- **Read-only demo:** a static React application with saved investigation data.
  It runs without Docker, a backend, or an API key and can be deployed to Vercel.
- **Full local stack:** the complete workflow with live telemetry, durable
  orchestration, model-assisted diagnosis, human approval, and sandboxed repair
  verification.

> [!NOTE]
> IncidentLab is a portfolio and educational project, not a production incident
> response platform. It operates on controlled scenarios and does not deploy or
> merge code automatically.

## Highlights

- Deterministic connection-pool exhaustion and inventory-underflow incidents
- OpenTelemetry traces, Prometheus metrics, and Loki logs
- Durable, retry-safe orchestration with Temporal
- Evidence artifacts and proposed diffs protected by SHA-256 integrity checks
- Structured GPT-5.4 Mini diagnosis with validated evidence citations
- Human approval before repair generation
- Fail-closed repair policy with path, size, secret, syntax, and patch checks
- Network-disabled, non-root Docker sandbox for independent verification
- React review console for evidence, diagnoses, diffs, verification, and audit history
- Static portfolio mode containing no API keys or runtime backend requests

## How it works

```text
Fault-injected service
        │
        ├── traces ─── Jaeger ──────┐
        ├── metrics ─ Prometheus ───┼── Evidence collector
        └── logs ──── Loki ─────────┘          │
                                               ▼
React console ── FastAPI ── PostgreSQL ── Temporal workflow
                                               │
                                      OpenAI diagnosis
                                               │
                                      Human approval gate
                                               │
                                       Repair policy
                                               │
                                               ▼
                                Trusted verifier ── Docker sandbox
```

The model proposes a diagnosis and a bounded source change, but it does not
decide whether verification passed. Verification outcomes are derived from fixed
checks and persisted artifacts. A separate trusted verifier controls the Docker
sandbox; the API and model worker do not receive the Docker socket.

## Static demo

The static demo is the quickest way to explore the interface. It includes two
curated, sanitized investigations with evidence, diagnoses, proposed repairs,
verification logs, audit events, and downloadable reports.

```sh
cd frontend
npm ci
npm run dev:demo
```

Open `http://localhost:5173`. No environment variables are required.

To create a production build:

```sh
npm run build:demo
```

### Deploy the demo to Vercel

Import this repository into Vercel and use the following settings:

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Framework Preset | Vite |
| Build Command | `npm run build:demo` |
| Output Directory | `dist` |

Do not add an OpenAI key or backend URL to the demo deployment. The checked-in
[`frontend/vercel.json`](frontend/vercel.json) defines the build, SPA routing,
and security headers. Saved data lives in
[`frontend/src/demo-data/dataset.json`](frontend/src/demo-data/dataset.json).

## Run the full stack locally

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop with Docker Compose
- An OpenAI API key with available credits

### Setup

Install the locked Python environment:

```sh
uv sync --frozen
```

Create the local configuration file:

```sh
cp .env.example .env
```

Add your key to `.env`:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5.4-mini
```

Never commit `.env` or expose an active key in logs, screenshots, issues, or
pull requests.

Start the application:

```sh
docker compose up -d --build --wait
```

Then open:

| Service | URL |
| --- | --- |
| IncidentLab console | `http://127.0.0.1:5173` |
| API | `http://127.0.0.1:8000` |
| Temporal UI | `http://127.0.0.1:8233` |
| Jaeger | `http://127.0.0.1:16686` |
| Prometheus | `http://127.0.0.1:9090` |

Confirm that the API is ready:

```sh
curl http://127.0.0.1:8000/ready
```

Stop the stack while preserving its volumes:

```sh
docker compose down
```

## Investigation lifecycle

1. A scenario starts an idempotent Temporal workflow.
2. The sample service reproduces a known failure.
3. IncidentLab gathers traces, metrics, logs, and repository context.
4. GPT-5.4 Mini produces structured hypotheses with evidence citations.
5. A reviewer approves or rejects repair generation in the console.
6. A bounded model response is converted into a deterministic unified diff.
7. The repair policy rejects unsafe or out-of-scope changes.
8. The trusted verifier applies accepted candidates in an isolated container.
9. Fixed checks produce the final result and a deterministic report.

## Development

Run backend checks:

```sh
.venv/bin/ruff check incidentlab sample_service tests migrations scripts
.venv/bin/ruff format --check incidentlab sample_service tests migrations scripts
TEST_DATABASE_ADMIN_URL=postgresql://incidentlab:incidentlab-local@127.0.0.1:55432/postgres \
  .venv/bin/python -m unittest discover -s tests -v
```

The migration tests require the Compose PostgreSQL service.

Run frontend checks:

```sh
cd frontend
npm ci
npm run typecheck
npm test
npm run build
npm run build:demo
```

Run the complete offline release demonstration:

```sh
.venv/bin/python scripts/demo_release.py
```

## Project structure

```text
incidentlab/       API, workflows, persistence, evidence, policy, and verification
frontend/          React review console and static demo data
sample_service/    Fault-injected checkout service and replay utilities
scenarios/         Public scenario definitions and private evaluation truth
telemetry/         OpenTelemetry Collector, Prometheus, and Loki configuration
migrations/        Alembic database migrations
scripts/           Verification, evaluation, and operational utilities
tests/             Backend test suite
docs/              Architecture, security, sandbox, and evaluation documentation
```

## Security model

- Telemetry, repository content, and model output are treated as untrusted input.
- Every diagnosis citation must resolve to stored evidence.
- Raw artifacts are size-limited and hash-verified.
- Model-requested evidence lookups are typed, allowlisted, and capped.
- Repair generation requires explicit human approval.
- Proposed changes must target allowlisted files and apply cleanly to a pinned commit.
- Verification runs without network access, as a non-root user, with resource limits.
- GitHub integration is optional, disabled by default, and limited to draft pull requests.

For more detail, see the [architecture](docs/architecture.md),
[threat model](docs/threat-model.md), [sandbox design](docs/sandbox.md), and
[evaluation methodology](docs/evaluation.md).

## Optional GitHub draft pull requests

Verified repairs can be published as draft pull requests through an opt-in
GitHub App integration. It is disabled by default and cannot merge or deploy.
Configuration details are documented in [`docs/github-app.yml`](docs/github-app.yml).

After configuring the integration, a passing candidate can be published with:

```sh
.venv/bin/python scripts/create_draft_pr.py RUN_ID --approved-by YOUR_NAME
```

## Limitations

- Scenarios are intentionally controlled and deterministic.
- Arbitrary repository onboarding and hosted multi-user operation are out of scope.
- Model quality and cost depend on the configured provider and model.
- The sandbox reduces risk but should not be treated as a hardened production boundary.

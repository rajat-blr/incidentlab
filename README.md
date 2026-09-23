# IncidentLab

IncidentLab is a local demonstration of evidence-backed incident diagnosis and verified repair. The [PRD](incidentlab-prd-and-build-plan.md) defines the full product and its numbered build sequence. Steps 1–4 are implemented: the seeded incident, telemetry, and a control-plane API with versioned contracts and PostgreSQL migrations.

## Current slice

The inventory service has a two-connection database pool. Failed checkout requests under the `pool_leak` fault leave connections checked out; a later valid request receives HTTP 503 through the checkout gateway. The healthy mode returns the connection and serves the valid request. This is a deliberately small, deterministic fixture, not a production checkout service.

Requires Python 3.12 or newer, `uv`, and Docker Desktop.

```sh
uv sync --frozen
docker compose up -d --build --wait
.venv/bin/python -m sample_service.telemetry_check
.venv/bin/python -m sample_service.demo --trials 20
.venv/bin/ruff check incidentlab sample_service tests migrations
.venv/bin/ruff format --check incidentlab sample_service tests migrations
TEST_DATABASE_ADMIN_URL=postgresql://incidentlab:incidentlab-local@127.0.0.1:55432/postgres \
.venv/bin/python -m unittest discover -s tests -v
```

The API is at `http://127.0.0.1:8000`. `GET /health`, `GET /ready`, and `GET /scenarios` are available. Run creation and workflow behavior begin in PRD Step 5. PostgreSQL is on host port `55432`; Temporal UI is at `http://127.0.0.1:8233`. The Compose stack runs the migration before starting the API. Stop it with `docker compose down` (volumes remain).

The telemetry check starts checkout and inventory in separate processes, replays the incident, and checks one distributed trace in Jaeger, pool metrics in Prometheus, and correlated logs in Loki. Jaeger is at `http://127.0.0.1:16686`; Prometheus is at `http://127.0.0.1:9090`. The [bounded incident queries](telemetry/queries.md) describe the signals.

To inspect the sample services manually after starting the Compose stack, use separate terminals:

```sh
.venv/bin/python -m sample_service.reset --database /tmp/incidentlab-checkout.sqlite3
INCIDENTLAB_DATABASE=/tmp/incidentlab-checkout.sqlite3 INCIDENTLAB_FAULT=pool_leak .venv/bin/python -m sample_service.app
.venv/bin/python -m sample_service.gateway
```

The gateway listens on `127.0.0.1:8765` and inventory on `127.0.0.1:8766` by default. `GET /health`, `GET /ready`, and `POST /checkout` are available. Post `{"sku":"widget","quantity":99}` twice, then `{"sku":"widget","quantity":1}` to the gateway to reproduce exhaustion. Set `INCIDENTLAB_FAULT=off` on inventory and reset the database to observe the healthy path.

The [PRD's numbered build plan](incidentlab-prd-and-build-plan.md#14-step-by-step-build-plan-dependency-order-no-schedule) is the implementation sequence and progress record. [ADR 0001](docs/adr/0001-first-vertical-slice.md) records the Step 1 decisions and trust boundary.

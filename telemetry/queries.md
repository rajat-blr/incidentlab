# Step 3 incident queries

These are the bounded queries for the first scenario. They use only the local development backends and a short incident window. Step 6 will turn them into collectors with immutable artifacts and explicit gap records.

| Signal | Query | What it shows |
| --- | --- | --- |
| Trace | Search Jaeger for `checkout` traces in the 5 minutes around the replay; filter spans by `incidentlab.request_id` | The checkout gateway span, its inventory client span, and the inventory server/database spans share one trace ID. The failed request's `db.pool.acquire` span has `db.pool.timeout=true`. |
| Pool capacity | Prometheus `incidentlab_db_pool_available{incidentlab_run_id="<run-id>"}` over the replay window | No connection remains available after the two rejected requests. |
| Pool timeout | Prometheus `incidentlab_db_pool_timeouts_total{incidentlab_run_id="<run-id>"}` | At least one timeout occurred after the pool reached zero. |
| Request outcome | Prometheus `incidentlab_gateway_requests_total{incidentlab_run_id="<run-id>",status="503"}` | The gateway returned a 503 for the valid checkout. |
| Log correlation | Loki `{service_name="inventory"} |= "<request-id>"` and `{service_name="checkout"} |= "<request-id>"` over the same 5-minute window | Both services record the same request ID and trace ID for a forwarded checkout. |

The first two independent signals are a failed acquisition span and the pool capacity/timeout metrics. A `503` alone only shows the symptom. The query set is intentionally small; later evidence collection must record missing telemetry rather than treating an empty result as proof of absence.

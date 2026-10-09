# Controlled incident scenarios

The suite covers four independent mechanisms in two cooperating components:
the inventory service and the checkout gateway. Each replay resets SQLite and
creates fresh service processes or handlers, so pool and cache state cannot
leak between trials.

| Scenario | Component / repair surface | Fault observation | Healthy control |
| --- | --- | --- | --- |
| `pool-exhaustion` | Inventory / `sample_service/app.py` | `409 → 409 → 503`; rejected requests consume pool slots | `409 → 409 → 200`; final stock is 9 |
| `inventory-underflow` | Inventory / `sample_service/app.py` | Quantity 11 succeeds with stock −1 | HTTP 409; stock remains 10 |
| `upstream-error-masking` | Gateway / `sample_service/gateway.py` | Inventory rejects with 409; gateway returns 200 with an error body | Gateway preserves 409; stock remains 10 |
| `mutation-response-cache` | Gateway / `sample_service/gateway.py` | Two purchase POSTs both return stock 9; only one stock decrement occurs | Responses show stock 9 then 8; both purchases reach inventory |

The new gateway defects exercise HTTP error propagation and mutation/cache
semantics. They broaden the suite beyond database resource and stock-guard
failures, while remaining within one deliberately small application.

## Reproduce without a model

```sh
.venv/bin/python scripts/demo_release.py
```

This runs every fault and its healthy control, followed by the four-scenario
offline regression evaluation. Public manifests live in `scenarios/`; private
truth labels live in `scenarios/private/` and are excluded from service and
sandbox images. Runtime code does not import the truth labels.

## Repair and verification

The active scenario selects exactly one source path for the model and repair
policy. Inventory repairs cannot edit the gateway; gateway repairs cannot edit
inventory. The approved candidate must touch the active mechanism's source
markers and still pass syntax, patch, scope, secret, and unsafe-code checks.

The trusted sandbox checker has fixed expectations baked into its image. It
checks HTTP statuses, response stock quantities, and persisted SQLite stock.
The cache scenario therefore cannot pass by returning a fabricated quantity.
Healthy integration checks also replay the other three inactive faults, proving
that repairing one fixture did not silently disable the others.

Rebuild the trusted image when adding scenarios or changing fixed checks:

```sh
docker build -f Dockerfile.sandbox -t incidentlab-sandbox:step8 .
```

Live runs pin source to a Git commit. Commit reviewed changes before using the
normal Compose setup, so the worker's source context and verifier archive match
the running scenario code. The recorded four-scenario evaluation uses an
isolated source snapshot and preserves its archive alongside the results.

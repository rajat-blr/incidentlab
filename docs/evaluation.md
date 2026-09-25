# Evaluation methodology

`scripts/evaluate.py` is the versioned offline release evaluation. It runs both
objective fixture scenarios repeatedly, compares IncidentLab's pipeline oracle with
a deterministic keyword baseline and an uncited one-shot baseline, executes six
adversarial probes, and writes:

- `report.json`: configuration, dataset digest, summaries, trials, and limitations;
- `metrics.csv`: one comparable row per scenario, trial, and evaluated system;
- `failures.json`: reproduction and adversarial failures, including an empty list.

Run it with:

```sh
.venv/bin/python scripts/evaluate.py --trials 5 --output evaluation-results/latest
```

Metrics are reproduction rate, diagnosis-label accuracy, citation validity, and
verified-repair rate. The offline `incidentlab` row is deliberately an upper-bound
oracle used for regression detection; it is not a claim about live Gemini accuracy.
Live model runs vary with model version, quota, and provider behavior and should be
reported separately with the pinned model and prompt IDs already stored per run.

The private truth files are never mounted into API, worker, or sandbox containers.
They are read only by local evaluation tooling. Publish failed trials alongside
successful trials; do not delete `failures.json` when it is empty.

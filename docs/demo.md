# Release demonstration

The browser-only frontend contains 21 saved investigations: nine curated histories
and all 12 trials from the latest live-model evaluation (six completed, six failed).
The recorded trials retain their full audit trails and hash-checked artifacts.
Four guided replays use successful saved templates and make no model calls.

```sh
cd frontend
npm ci
npm run dev:demo -- --port 5176 --strictPort
```

Open `http://localhost:5176`. To re-export every recorded evaluation trial:

```sh
.venv/bin/python scripts/export_demo_runs.py \
  docs/results/live-four-scenarios-matched-head-2026-10-09 --all-trials
```

Run the exporter from the repository root. Missing artifacts are fetched from
the report's API URL, and every displayed artifact must match its SHA-256 hash.

For a fast offline demonstration with no model key, run:

```sh
.venv/bin/python scripts/demo_release.py
```

The output first shows deliberate pool exhaustion (`409 → 409 → 503`) and then
recovery after a clean reset (`409 → 409 → 200`). It also shows a negative inventory
write and its healthy rejection. It then shows masked upstream errors (200
versus 409) and cached purchase responses (stock 9 → 9 versus 9 → 8), and
produces the evaluation artifacts in
`evaluation-results/demo/`.

For the full interactive path, start Compose, open `http://127.0.0.1:5173`, create a
run, inspect cited evidence, approve bounded generation from the overview dialog,
watch the trusted verifier update the run automatically, and export the report.
Stop and restart the worker while the run is waiting for approval to demonstrate
durable recovery.

The optional GitHub demonstration is intentionally separate. Configure a private
GitHub App from `docs/github-app.yml`, set the opt-in environment variables, then run
`scripts/create_draft_pr.py RUN_ID --approved-by NAME`. This records a second
approval and creates or reuses one draft PR; it never merges or deploys.

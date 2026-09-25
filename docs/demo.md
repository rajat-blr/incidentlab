# Release demonstration

For a fast offline demonstration with no model key, run:

```sh
.venv/bin/python scripts/demo_release.py
```

The output first shows deliberate pool exhaustion (`409 → 409 → 503`) and then
recovery after a clean reset (`409 → 409 → 200`). It also shows a negative inventory
write and its healthy rejection, then produces the evaluation artifacts in
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

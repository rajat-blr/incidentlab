# Optional GitHub draft PR integration

The local backend supports a separate, opt-in draft PR action after a candidate
has passed verification. The browser-only demo does not use this integration.
It does not merge PRs or deploy repairs.

## App and webhook setup

Use `docs/github-app.yml` as a manifest template, replacing its webhook and
redirect URLs with your reachable local tunnel. Install the App on the target
repository with `metadata: read`, `contents: write`, and `pull_requests: write`.
Installation events with missing required permissions or write access to
administration, deployments, or workflows are rejected.

Set `GITHUB_WEBHOOK_SECRET` in the local environment and recreate the API
container. `POST /integrations/github/webhook` checks the HMAC signature and
validates permissions on `installation` and `installation_repositories` events.
The endpoint acknowledges events; it does not start investigations or exchange
App credentials for tokens. Supply a current installation token yourself.

## Create an approved draft

Configure these variables in the shell running the script:

- `DATABASE_URL`: the local investigation database URL (on the host, use
  `127.0.0.1:55432` for the default Compose PostgreSQL instance).
- `GITHUB_INTEGRATION_ENABLED=true`.
- `GITHUB_REPOSITORY=owner/repository`.
- `GITHUB_INSTALLATION_TOKEN`: a current token for that installation.

After reviewing a run and its passing candidate, invoke:

```sh
.venv/bin/python scripts/create_draft_pr.py RUN_UUID --approved-by YOUR_NAME
```

This command records a separate `create_draft_pr` approval, selects the
highest-ranked passing candidate, applies its diff to the pinned commit, and
creates a draft on `incidentlab/run-RUN_UUID`. Retries retrieve the existing
draft; an existing non-draft PR fails closed. The script records the resulting
PR URL in the run's audit history. It is a CLI action, not a console button.

The current PR body links to the local console at `http://127.0.0.1:5173`;
remote reviewers need access to that instance or an exported report.

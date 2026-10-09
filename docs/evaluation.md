# Evaluation methodology

## Live-model evaluation

`scripts/evaluate_live.py` creates fresh investigations through the live API,
records approval under the automated actor `live-evaluation-v1`, and waits for
the trusted verifier's terminal outcome. It uses the existing model worker and
real telemetry; it does not inject fixture diagnoses or oracle repairs.

Start the local stack and sandbox with a working `OPENAI_API_KEY` in `.env`:

```sh
docker build -f Dockerfile.sandbox -t incidentlab-sandbox:step8 .
docker compose up --build -d --wait
.venv/bin/python scripts/evaluate_live.py --model gpt-5.4-mini --trials 3 \
  --output evaluation-results/live
```

`--model` must match the worker's `OPENAI_MODEL`. It checks provenance; it does
not reconfigure the worker. Prefer a dated provider model ID when available.
The current configured ID is an alias, not an immutable provider snapshot.
After changing `.env`, recreate the worker before rerunning:

```sh
docker compose up -d --force-recreate worker
```

The runner writes `report.json`, `metrics.csv`, and `failures.json` after every
trial. It returns a nonzero exit code if any trial fails. Use a new output
directory for each batch to preserve failed attempts. API readiness failures
are preflight errors, not model trials. A timeout requests cancellation and
retains the partial report.

Cited evidence and all verification check logs are exported to `artifacts/`,
named by their actual SHA-256 hashes. `artifact-manifest.json` maps the original
API references to these portable files.

### Definitions

- **Reproduction rate:** trials with a persisted `reproduction_recorded` fact
  divided by all attempted trials.
- **Citation validity (trial rate):** trials with a real, matching-model
  diagnosis whose citations all resolve within that run, whose supporting IDs
  are not gaps, and whose cited artifacts match their stored SHA-256 hashes,
  divided by all attempted trials. No diagnosis counts as an unsuccessful
  attempt. This measures citation integrity, not semantic entailment.
- **Citation-level validity:** resolved IDs divided by emitted citations;
  undefined when no citations were emitted. Counts are retained separately.
- **Verified-repair rate:** completed trials with a valid cited diagnosis,
  matching-model diagnosis and repair usage, and at least one trusted verifier
  `PASS` whose check artifacts pass hash validation, divided by all attempts.
  Failed, inconclusive, timed-out, and policy-rejected trials stay in the
  denominator.

Trials preserve run IDs, pinned commits, model IDs, prompt versions, usage,
candidate diffs, checks, and audit events. Usage is recorded by successful
activities and may omit rejected calls; zero recorded tokens after a provider
error is not a billing assertion. Retries within an activity remain one trial.

### Current four-scenario batch: 2026-10-09

The expanded benchmark uses isolated source snapshot
`36a20fd72be99e1ebadad1deee620c311dbbe177`, model `gpt-5.4-mini`, and successful
activity provenance `diagnosis-v2` / `repair-v8`. A detached local copy of this
snapshot supplies the worker's Git metadata and pinned source. Its HEAD matches
the pinned commit, while the developer's active branch is unchanged.

| Scenario | Trials | Reproduction | Valid cited diagnosis | Verified repair | Failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pool exhaustion | 3 | 3/3 | 2/3 | 2/3 | 1 |
| Inventory underflow | 3 | 3/3 | 2/3 | 2/3 | 1 |
| Upstream error masking | 3 | 3/3 | 2/3 | 2/3 | 1 |
| Mutation response cache | 3 | 3/3 | 0/3 | 0/3 | 3 |
| **Total** | **12** | **12/12 (100%)** | **6/12 (50%)** | **6/12 (50%)** | **6** |

The six unsuccessful trials stopped at diagnosis: three misused gap evidence,
two exceeded the follow-up budget, and one requested another query during
correction. No candidate was produced for those trials. All 44 emitted citation
IDs resolved within their runs. Matching Git evidence does not remove genuine
telemetry gaps, such as the absence of an upstream request when the gateway
serves a cached POST.

See [report.json](results/live-four-scenarios-matched-head-2026-10-09/report.json),
[failures.json](results/live-four-scenarios-matched-head-2026-10-09/failures.json),
and the [artifact manifest](results/live-four-scenarios-matched-head-2026-10-09/artifact-manifest.json).
Every passing candidate's integration check verifies that the other three
inactive scenarios still reproduce; replay checks also inspect persisted stock.

### Earlier four-scenario snapshot setup

The first [12-trial expansion batch](results/live-four-scenarios-2026-10-09/report.json)
used the same source snapshot but read Git HEAD metadata from the active branch.
The collector therefore emitted an explicit Git gap. That batch reproduced
12/12, accepted cited diagnoses and verified repairs in 6/12, and failed six
diagnoses (five involving gap misuse, one exceeding the follow-up budget).
It is retained, rather than replaced by the corrected setup.

The cache scenario achieved two independently verified repairs in that earlier
batch, even though all three cache diagnoses in the current batch were rejected.
This variability is visible in the saved reports. The browser demo's new gateway
histories are exported from successful trials in the earlier batch and preserve
their actual evidence, candidate diffs, and verification logs. They are examples,
not a representative success-rate sample.

The [source archive](results/live-four-scenarios-2026-10-09/source.tar.gz) contains
the exact evaluated snapshot. It excludes local credentials and scratch files.
The two expansion batches together reproduced 24/24 and verified 12/24 repairs.
Together with the original batches below, all 36 attempts are retained: 36/36
reproductions, 17/36 valid cited diagnoses, 17/36 verified repairs, and 19 failures.
These totals span different source and prompt setups and are audit counts, not
an accuracy estimate for a single fixed configuration.

### Original two-scenario model batch: 2026-10-09

After updating credentials, a [fresh six-trial batch](results/live-2026-10-09-rerun/report.json)
ran against the same commit and configured model, with successful activity
provenance `diagnosis-v2` and `repair-v7`:

| Scenario | Trials | Reproduction rate | Citation validity (trial rate) | Verified-repair rate | Failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pool exhaustion | 3 | 3/3 (100%) | 2/3 (66.7%) | 2/3 (66.7%) | 1 |
| Inventory underflow | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0 |
| **Total** | **6** | **6/6 (100%)** | **5/6 (83.3%)** | **5/6 (83.3%)** | **1** |

Pool trial 2 failed with `DiagnosisError: follow-up query budget exhausted`.
That run produced no accepted diagnosis or candidate and remains in all rate
denominators. See [failures.json](results/live-2026-10-09-rerun/failures.json).
The runner's nonzero exit code is expected for this batch because one trial
failed; it is not evidence that the report export failed.

The five completed trials emitted 33 citations, all resolving within their
respective runs. Cited evidence and verification logs were independently
downloaded and hash-checked: 55 artifact references are preserved in the
[manifest](results/live-2026-10-09-rerun/artifact-manifest.json).
Every passing candidate has seven recorded verification checks. Candidate
diffs and exact run IDs are included in the report for inspection.

### Earlier authentication batch: 2026-10-09

The [six-trial report](results/live-2026-10-09/report.json) records three attempts
per scenario against commit `a8c1bd576f633b6c0202b5cc68918874ae575053`, with
`gpt-5.4-mini` configured. All six reproduced; all six diagnosis requests failed
with `AuthenticationError`. There were zero hypotheses, citations, repair
candidates, or verification outcomes. No model or prompt provenance was recorded
by a successful activity. This batch documents a provider configuration failure
and **does not establish live model quality**. All failures are retained in
[failures.json](results/live-2026-10-09/failures.json).

Across both batches: 12/12 reproduced, 5/12 produced valid cited diagnoses,
5/12 produced verified repairs, and seven failed. The README shows both batches
and the combined denominator to make the configuration failure visible.

These historical batches cover the original two inventory defects. The current
suite adds two gateway defects, [upstream error masking and mutation response
caching](scenarios.md). Even the expanded suite cannot support claims about
unfamiliar applications or repositories.

## Offline regression evaluation

`scripts/evaluate.py` is the versioned offline release evaluation (`evaluation-v2`). It runs all four
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
oracle used for regression detection; it is not a claim about live model accuracy.
Live model runs vary with model version, quota, and provider behavior and should be
reported separately with the pinned model and prompt IDs already stored per run.

The private truth files are never mounted into API, worker, or sandbox containers.
They are read only by local evaluation tooling. Publish failed trials alongside
successful trials; do not delete `failures.json` when it is empty.

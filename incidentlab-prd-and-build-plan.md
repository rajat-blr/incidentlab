# IncidentLab — Product Requirements Document and Step-by-Step Build Plan

**Status:** Draft for implementation  
**Product type:** Developer tool / portfolio-quality engineering project  
**Primary audience:** Engineers and incident responders working on instrumented services  
**Working name:** IncidentLab

## 1. Product summary

IncidentLab turns a reproducible service incident into an evidence-backed diagnosis and a verified, human-reviewable repair proposal. It collects telemetry and repository context, tests root-cause hypotheses, proposes a narrowly scoped code patch, replays the incident in an isolated environment, and explains the result. It does **not** merge code or deploy to production.

The first release is a local, self-hosted demonstration against a purpose-built sample application. It should feel like a real product: a user can trigger an incident, inspect the evidence and workflow history, approve repair generation, compare a candidate patch against a baseline, and export a remediation report. GitHub draft-PR creation is an optional later integration.

### Product promise

> “Show me why this incident happened, what evidence supports that conclusion, and whether a proposed fix actually resolves it without breaking the service.”

### Core differentiation

The value is **verified remediation**, not the number of agents. LLM components propose hypotheses and patches; deterministic components collect facts, enforce policy, execute tests, and decide whether verification passed.

## 2. Problem and opportunity

Incident response often requires engineers to move between dashboards, traces, logs, deployment history, and source code. A plausible explanation is not enough: the explanation must cite evidence, and a code change must be tested against the original failure and regressions. Generic AI assistants can draft explanations and patches, but their outputs are hard to audit and may be untested.

IncidentLab focuses on one narrow loop: **reproduce → investigate → propose → verify → review**. The initial product uses synthetic, known-ground-truth incidents so every claim can be evaluated.

## 3. Users and jobs to be done

| User | Job | Needed outcome |
|---|---|---|
| Service engineer | Understand an unfamiliar incident | Ranked hypotheses with direct links to supporting and contradicting evidence |
| Incident lead | Decide whether a repair is worth pursuing | Clear workflow state, confidence caveats, verification result, and audit history |
| Reviewer | Assess a proposed code change | Small diff, reproduction proof, test results, policy findings, and known limitations |
| Project evaluator/interviewer | Assess engineering quality | Reproducible demo, failure recovery, measurable results, security boundaries, and trade-off documentation |

The primary user is a service engineer. The evaluator is an important secondary audience, but portfolio signaling must not distort the product into unnecessary infrastructure.

## 4. Goals, non-goals, and operating assumptions

### Goals

1. Reproduce at least two distinct incidents with documented ground truth.
2. Produce hypotheses whose cited evidence IDs resolve to actual, inspectable telemetry or repository records.
3. Verify a patch by proving the incident exists before the patch and is absent after it, while regression checks still pass.
4. Resume a run after a worker crash or transient model/tool failure without duplicating side effects.
5. Keep code changes behind explicit human approval; never merge or deploy automatically.
6. Provide per-run traces, costs, timings, decisions, and artifact lineage.
7. Make a local demo reproducible with a single setup path and a documented command sequence.

### Non-goals for the initial release

- Autonomous production operations, canary deployments, rollback, or merges.
- Arbitrary repositories, languages, or incident types.
- A general chat assistant or autonomous agent marketplace.
- Free-form model-generated shell commands.
- A vector database, Kubernetes, Kafka, or graph RAG unless evaluation shows a need.
- Security claims that rootless containers are sufficient isolation for hostile, public, multi-tenant code execution.

### Initial assumptions

- Target application: a small, instrumented service system maintained in this repository.
- Supported repository language: one language only; choose Go for the demo service if it matches the author's strengths, otherwise Python is acceptable.
- Control plane: Python 3.12+, FastAPI, Pydantic v2, Temporal, PostgreSQL.
- Development runtime: Docker Compose. Model provider is configurable through a thin internal adapter.
- The initial user is trusted and runs the product locally. Public, multi-tenant use requires a stronger sandbox and separate security review.

## 5. Scope and release boundary

### Required first-release capabilities

- Run a seeded incident scenario and preserve its ground-truth manifest separately from model inputs.
- Create an incident run with a unique ID and durable state.
- Collect a bounded incident bundle: metrics, traces, logs, deployment/commit metadata, and selected source files.
- Normalize facts into evidence records with provenance and stable IDs.
- Generate a small set of structured root-cause hypotheses, including supporting and contradicting evidence.
- Validate hypothesis schemas, citation IDs, allowed tool requests, and budget constraints.
- Pause for human approval before patch generation.
- Generate at most two patches within an allowed directory/file scope.
- Run each patch in a fresh sandbox against build, static, regression, and incident-replay checks.
- Rank only candidates that pass mandatory gates.
- Produce a remediation report and a web UI for inspecting the full run.
- Export machine-readable evaluation results for repeated scenario runs.

### Optional follow-on capabilities

- GitHub App integration that creates a **draft** PR after approval.
- More incident scenarios and support for another repository language.
- External artifact storage, stronger sandboxing, organization accounts, and live incident ingestion.

## 6. End-to-end user journey

1. **Select and start:** User selects a scenario and starts a run. The UI shows scenario description but does not reveal the ground-truth root cause to the model.
2. **Reproduce:** The platform starts the sample service, injects the fault, generates traffic, and confirms that the failure condition occurred. If not, the run stops as `REPRODUCTION_FAILED` rather than producing an unsupported diagnosis.
3. **Collect:** The platform captures a fixed time window of metrics, traces, logs, recent changes, and relevant source references. Each item receives a stable evidence ID.
4. **Diagnose:** The diagnosis component returns at most three hypotheses. The system rejects invalid evidence citations and may perform a bounded number of approved follow-up queries.
5. **Review:** The user sees the hypothesis, evidence, counter-evidence, uncertainty, and investigation trace. They approve or reject repair generation.
6. **Repair:** The patch generator receives the approved hypothesis, failing reproduction, relevant files, and edit policy. It returns a diff, not executable instructions.
7. **Verify:** For each patch, a fresh baseline run proves the incident still reproduces, then the patch is applied and build, static, regression, and incident replay checks run. Results and raw artifacts are saved.
8. **Decide:** Deterministic rules disqualify failed candidates and rank eligible ones. The UI shows why each candidate passed or failed.
9. **Export:** The user downloads a report or, in a later release, approves creation of a draft PR. The run remains auditable after completion.

## 7. Functional requirements

Priority labels: **P0** = necessary for first release; **P1** = valuable after the core loop works.

### FR-01 — Scenario catalog (P0)

Each scenario has an ID, version, setup command, fault-injection method, traffic profile, expected failure signal, ground-truth root cause, expected affected files, and deterministic reset procedure. Ground truth is available to evaluation only, not to the diagnosis or repair model.

**Acceptance:** A scenario can be reset and replayed repeatedly; the failure signal is observed before any AI call. The scenario manifest is versioned with the repository.

### FR-02 — Run creation and durable state (P0)

An API/CLI starts a run using a scenario ID and an idempotency key. One run maps to one durable Temporal workflow. State transitions are recorded in PostgreSQL and exposed in the UI.

**Acceptance:** Repeating the request with the same idempotency key returns the same run. Restarting an API or worker does not lose run state or duplicate an approved external action.

### FR-03 — Evidence collection and normalization (P0)

Collectors fetch bounded data from telemetry stores and Git. Each normalized evidence item includes: ID, run ID, kind, source, query or retrieval method, observed time/window, service, summary, immutable artifact reference, and content hash. The collector records gaps and query errors explicitly.

**Acceptance:** Every evidence citation opens the original snippet/trace/metric view or saved artifact. Missing telemetry is shown as missing, not silently treated as proof of absence.

### FR-04 — Structured diagnosis (P0)

The diagnosis model returns at most three hypotheses with summary, mechanism, supporting evidence IDs, contradicting evidence IDs, confidence category, and proposed checks. Avoid presenting a numeric probability unless it has been calibrated against evaluation data.

**Acceptance:** Invalid schemas, nonexistent citations, or unauthorized checks are rejected and logged. The final view displays both supporting and contradicting evidence. Model text from logs and code is treated as untrusted input.

### FR-05 — Bounded investigative tools (P0)

The diagnosis component may request allowlisted, typed tools such as `query_metric`, `fetch_trace`, `search_logs`, and `search_repository`. Every request has a bounded time window, result size, timeout, and per-run call budget.

**Acceptance:** A run terminates or asks for human intervention when the budget is exhausted; it cannot loop indefinitely or execute arbitrary commands.

### FR-06 — Human approval and policy (P0)

Repair generation requires an explicit user action. The policy engine checks allowed paths, patch size, forbidden file types, tool scopes, model budget, and the presence of secrets. Approval decisions are recorded with actor and timestamp.

**Acceptance:** A rejected or unapproved diagnosis cannot trigger patch generation. A policy violation cannot be overridden by persuasive model output.

### FR-07 — Patch generation (P0)

The repair component returns a unified diff plus a concise explanation and expected behavioral change. It cannot modify scenario ground-truth files, evaluation fixtures, CI policy, dependencies, or infrastructure definitions in the first release.

**Acceptance:** The diff applies cleanly to the pinned repository commit, stays within scope, and has no side effects until verification. Invalid or oversized diffs are rejected.

### FR-08 — Isolated verification (P0)

Each candidate uses a fresh work directory and isolated runtime. Verification includes: baseline incident reproduction, patch application, compilation, static checks, unit tests, integration tests, repeated incident replay, and a bounded performance check. Each check saves exit status, command/configuration, timestamps, logs, and artifact hashes.

**Acceptance:** A patch is never labeled “verified” unless the pre-patch incident reproduces, the post-patch incident does not, and required regression checks pass. A flaky or inconclusive result is labeled `INCONCLUSIVE`, not `PASS`.

### FR-09 — Candidate ranking (P0)

Mandatory gates disqualify policy violations, failed builds/tests, missing baseline reproduction, and persistent incident failure. Eligible patches are ranked by documented, deterministic criteria such as regression coverage, performance delta, and diff complexity. The score version is stored with each run.

**Acceptance:** Given identical verification facts and score version, ranking is identical. The UI explains each disqualification and rank.

### FR-10 — Run UI and report (P0)

The UI provides an incident list, run timeline, evidence browser, hypotheses, approval action, patch diff, verification matrix, costs, and audit trail. A report can be exported as Markdown and JSON. The report distinguishes observed facts, model hypotheses, deterministic results, and user decisions.

**Acceptance:** A reviewer can understand the proposed root cause and the verification outcome without reading worker logs or database tables.

### FR-11 — Evaluation harness (P0)

An evaluation command runs scenarios without exposing ground truth to models, records standardized results, and supports repeated runs with model/prompt/version metadata. A deterministic retrieval/rules baseline and a one-shot model baseline are included.

**Acceptance:** Evaluation output includes root-cause accuracy, evidence-citation validity, reproduction reliability, repair success, regression failures, unsafe-action rejection, run time, and model cost. Results can be compared across versions.

### FR-12 — Draft PR integration (P1)

After human approval, a scoped GitHub App may create a branch and draft PR containing the patch and verification report. The system never merges or deploys it.

**Acceptance:** Webhook signatures are checked, permissions are minimal, repeated requests do not duplicate PRs, and the report links back to the local run.

## 8. Workflow and failure semantics

```text
CREATED → REPRODUCING → COLLECTING → DIAGNOSING
                                       ↓
                           AWAITING_REPAIR_APPROVAL
                              ↓ approved       ↓ rejected
                           GENERATING          CLOSED
                              ↓
                           VERIFYING → REPORTING → COMPLETED

Any active state → FAILED / CANCELLED
Verification may end with NO_VERIFIED_CANDIDATE rather than COMPLETED_WITH_FIX.
```

The workflow controls ordering and retries. Side-effecting work happens in Activities, not in deterministic workflow code. Every side-effecting Activity needs a stable idempotency key. Retry only transient errors; schema/policy failures should fail fast. Set explicit timeouts, retry limits, heartbeats for long verification jobs, and cleanup on cancellation. Persist enough information to explain a stopped run, including the last completed step and failure category.

The user-facing statuses `FAILED`, `INCONCLUSIVE`, and `NO_VERIFIED_CANDIDATE` are distinct. A system failure is not evidence that a hypothesis or patch is wrong.

## 9. Data and API contracts

### Core entities

- `Scenario`: versioned setup, fault, traffic, expected signal, and private evaluation truth.
- `IncidentRun`: scenario version, pinned repository commit, state, timestamps, idempotency key, workflow ID.
- `EvidenceItem`: provenance, immutable artifact reference, content hash, and display summary.
- `Hypothesis`: claim, mechanism, supporting/contradicting IDs, validation status, and model metadata.
- `Approval`: actor, action, decision, policy version, timestamp.
- `RepairCandidate`: diff artifact, scope, target commit, generator metadata.
- `VerificationRun`: per-check outcomes, artifacts, environment/image digest, resource usage.
- `AuditEvent`: append-only state/action record with correlation ID.
- `ModelUsage`: provider/model identifier, prompt version, token counts, latency, estimated cost.

### Initial API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/scenarios` | List safe scenario metadata |
| `POST` | `/runs` | Start run with scenario ID and idempotency key |
| `GET` | `/runs/{id}` | Current state and summary |
| `GET` | `/runs/{id}/events` | Paginated timeline |
| `GET` | `/runs/{id}/evidence` | Evidence index and artifact links |
| `GET` | `/runs/{id}/hypotheses` | Structured diagnosis |
| `POST` | `/runs/{id}/repair-approval` | Approve/reject repair generation |
| `GET` | `/runs/{id}/candidates` | Diffs, checks, rank, disqualifications |
| `GET` | `/runs/{id}/report` | Markdown/JSON report |
| `POST` | `/runs/{id}/cancel` | Cancel and clean up |

Use versioned Pydantic request/response models. Keep model prompts and raw artifacts outside public API responses by default; expose sanitized views. Use PostgreSQL for state and metadata, and object-style storage for large immutable artifacts. Do not use Temporal history as the sole user-facing audit store.

## 10. Security, trust, and privacy requirements

1. Treat logs, traces, code comments, filenames, commit messages, and model output as untrusted data. Never let them redefine tool permissions or system instructions.
2. Use explicit tool allowlists and typed arguments. No general shell tool is exposed to the model.
3. Separate API/model workers from the sandbox worker. Do not mount the Docker socket into the web/API process.
4. Run verification containers without privileged mode or host networking; restrict writable mounts, network egress, CPU, memory, PIDs, wall time, and output size. Use pinned images and record image digests.
5. Scan and redact secrets before model submission and report export. Never place credentials in generated patches or sandbox environment variables unless essential to a controlled test.
6. Require user approval before generating a patch and again before any external write such as draft-PR creation.
7. Retain an append-only audit trail of tool calls, approvals, policy decisions, and external writes.
8. State the security boundary honestly: rootless Docker reduces privilege but is not, by itself, a hardened boundary for arbitrary hostile code. A public multi-tenant product would need stronger isolation such as microVMs, egress controls, tenancy isolation, and dedicated security review.

## 11. Non-functional requirements and proposed quality bars

These are initial **targets to test and revise**, not claims of achieved performance.

| Area | Requirement / proposed bar |
|---|---|
| Reproducibility | Each seeded incident reproduces in at least 19 of 20 clean local runs before AI is introduced. |
| Evidence integrity | 100% of cited evidence IDs resolve to saved source artifacts; no fabricated citation is displayed. |
| Durability | Killing a worker during a run does not lose the run or duplicate an approved external action. |
| Isolation | A candidate cannot write outside its workspace or reach the Docker host through mounted sockets. |
| Boundedness | Each model/tool step has a timeout, retry cap, result-size cap, and per-run budget. |
| Observability | Every run has correlated traces, structured logs, step durations, model usage, and failure categories. |
| Explainability | Every pass/fail and ranking decision is derivable from stored verification facts and policy version. |
| Portability | Documented setup works on a clean supported development machine with pinned dependencies/images. |
| Accessibility | Main UI flow supports keyboard navigation, readable status labels, and non-color-only pass/fail cues. |

## 12. Success metrics and evaluation design

**North-star metric:** Percentage of seeded incidents that end with a correctly diagnosed root cause and a patch that passes verified replay and regression gates, with zero unauthorized actions.

Track separately:

- Scenario reproduction reliability.
- Top-1 and top-3 root-cause accuracy against hidden ground truth.
- Evidence citation validity and missing-evidence rate.
- Baseline reproduction and post-patch remediation rates.
- Build, test, static-check, and performance gate pass rates.
- False “verified” rate (the most important failure to minimize).
- Unsafe-action attempt and rejection counts.
- Median and tail run duration; model tokens and cost per incident.
- Variance across repeated runs and comparison with deterministic and one-shot baselines.

Maintain a versioned evaluation dataset. Pin scenario versions, target commits, prompts, model identifiers, image digests, and scoring rules in every result. Run repeated trials rather than showcasing a single successful trace. Publish both successful and failed examples in project documentation.

## 13. UX requirements

The main screen should answer four questions quickly: **What happened? Why does the system think so? Did the proposed fix work? What did it cost?**

Required views:

1. **Scenario/run list:** State, service, incident type, start time, and final outcome.
2. **Run timeline:** Each step, duration, retry, failure, approval, and current status.
3. **Evidence explorer:** Grouped metrics, trace spans, log clusters, commits, and files; clickable citation IDs.
4. **Diagnosis panel:** Ranked hypotheses, evidence for/against, uncertainty, and approved checks.
5. **Patch review:** Side-by-side diff, scope/policy result, candidate comparison, and approval control.
6. **Verification matrix:** Before/after incident signal, build, tests, static analysis, performance, and raw logs.
7. **Report/audit view:** Exportable conclusion, limitations, model usage, policy events, and artifact hashes.

Use plain language such as “Incident no longer reproduces in 5 replay runs” rather than a generic “AI confidence: 92%” badge. Show `INCONCLUSIVE` prominently when reproduction or verification evidence is weak.

## 14. Step-by-step build plan (dependency order; no schedule)

Each step has a tangible output and an exit check. Do not advance because an integration looks impressive; advance when the current step is reproducible and tested.

**Implementation progress (2026-09-22):**

- **Step 1 complete.** First-slice decisions, scenario contract, and threat boundary are recorded in `docs/adr/0001-first-vertical-slice.md` and `scenarios/`.
- **Step 2 complete.** The checkout fixture, reset command, fault switch, health endpoints, and HTTP replay are implemented. The 20-trial replay produced 20/20 fault reproductions and 20/20 healthy controls after a fresh reset for each trial.
- **Step 3 complete.** Checkout and inventory emit correlated OpenTelemetry traces, metrics, and structured logs through the local Collector to Jaeger, Prometheus, and Loki. `.venv/bin/python -m sample_service.telemetry_check` verifies one trace across both services, a failed database acquisition span, zero available pool connections, a timeout metric, and matching backend logs. Bounded queries are in `telemetry/queries.md`.
- **Step 4 complete.** The API, workflow, evidence, model adapter, policy, sandbox, verification, and evaluation packages exist. Versioned Pydantic contracts, PostgreSQL tables and Alembic migration, locked dependencies, Ruff checks, tests, and a full Compose stack are in place. `docker compose up -d --build --wait` started the API and dependencies; `/ready` and the public `/scenarios` response succeeded. A fresh PostgreSQL database passed migration upgrade and downgrade tests, and `alembic check` found no schema drift.

The next step is **Step 5 — Implement durable run orchestration without AI**. Later steps remain in the order below.

### Step 1 — Freeze the vertical slice

Choose one sample service language, one incident (prefer database connection-pool exhaustion), one model provider, and one local development environment. Write the scenario contract and threat boundaries. Record a short architecture decision explaining why deployment, arbitrary repositories, and extra infrastructure are deferred.

**Exit check:** Someone can state exactly what the first demo will and will not do, and the scenario has objective failure/repair criteria.

### Step 2 — Build the target application and fault injector

Create a small checkout-like service, a dependent service or database, deterministic seed data, traffic generator, and a switchable fault. Add health endpoints and a reset command. Keep the known-good and faulty code paths or commits pinned.

**Exit check:** The fault causes a measurable, repeatable failure; reset returns the system to baseline. Run it repeatedly before adding AI.

### Step 3 — Instrument the target system

Emit OpenTelemetry traces and metrics with correlation IDs and structured logs. Route them through a local Collector to a development telemetry backend. Define a small set of incident queries rather than scraping every possible signal.

**Exit check:** A request can be followed across services; the fault is visible in at least two independent signals.

### Step 4 — Create repository skeleton and contracts

Set up Python packages for API, workflow, evidence, model adapter, policy, sandbox, verification, and evaluation. Add typed schemas, migrations, linting, formatting, tests, dependency lockfile, and Compose setup. Define the scenario, evidence, hypothesis, patch, and verification schemas before implementing prompts.

**Exit check:** A clean checkout starts the API and dependencies; schema and migration tests pass.

### Step 5 — Implement durable run orchestration without AI

Create the Temporal workflow and Activities for reproduction, evidence collection, waiting for approval, verification placeholder, and reporting. Add idempotency keys, retries, timeouts, heartbeats, cancellation, and state persistence. Use deterministic placeholder diagnosis and repair outputs.

**Exit check:** Kill and restart a worker mid-run; the workflow resumes with correct state and no duplicate side effects.

### Step 6 — Normalize and store evidence

Implement bounded collectors for telemetry and Git metadata. Save raw artifacts and normalized evidence with hashes. Add tests for empty, late, duplicate, and malformed telemetry. Build evidence APIs before adding diagnosis.

**Exit check:** Every displayed fact can be traced back to an immutable saved artifact; missing data is explicit.

### Step 7 — Add diagnosis with strict boundaries

Add a single model adapter and prompt versioning. Return structured hypotheses only. Validate schemas, citations, tool names/arguments, and budgets; allow a small number of typed follow-up queries. Build the diagnosis UI and approval action.

**Exit check:** Prompt injection in a log line cannot cause an unauthorized tool call, and nonexistent citations never appear as valid evidence.

### Step 8 — Build the sandbox independently

Implement a verification runner that works with a manually supplied patch before connecting the repair model. Create a clean copy at a pinned commit, apply a diff, run fixed commands, enforce resource/network/mount limits, collect artifacts, and clean up on success/failure/cancellation.

**Exit check:** The runner can verify a known-good patch, reject a known-bad patch, and contain a malicious/invalid patch within documented limits.

### Step 9 — Add repair generation and deterministic policy

Feed only the approved hypothesis, selected repository context, and failing reproduction into the patch generator. Restrict edit paths and patch size. Validate and store at most two candidate diffs; do not execute model-provided commands.

**Exit check:** Forbidden files and malformed diffs are rejected before sandbox execution; an approved candidate reaches the independent verifier.

### Step 10 — Implement before/after verification and ranking

Require baseline reproduction, then build/static/regression/replay checks after patching. Repeat incident replay enough to identify flakiness. Save all raw outputs and derive pass/fail from facts. Implement versioned deterministic ranking and `INCONCLUSIVE` handling.

**Exit check:** No patch can be marked verified when the baseline did not fail or the post-patch replay still fails; ranking is repeatable from stored results.

### Step 11 — Complete the user-facing review flow

Build run list, timeline, evidence explorer, hypothesis review, diff view, verification matrix, report export, and audit view. Ensure approvals and cancellations work after page reloads and worker restarts.

**Exit check:** A fresh reviewer can reach a justified approve/reject decision using only the UI and exported report.

### Step 12 — Add evaluation and adversarial cases

Add a second distinct scenario, hidden ground truth, repeated-run harness, deterministic and one-shot baselines, and metrics export. Include failures such as worker termination, model timeout, duplicate API request, malformed structured output, poisoned log text, and flaky incident reproduction.

**Exit check:** A single evaluation command produces comparable results and a failure report; documentation includes honest failure cases, not just successful examples.

### Step 13 — Add optional GitHub draft-PR integration

Only after the local report and approval flow are solid, add a scoped GitHub App. Validate webhook signatures and installation permissions. Use an idempotent branch/PR operation, create **draft** PRs only, and include the report and verification links.

**Exit check:** Repeated or retried approval cannot create duplicate PRs; the application cannot merge or deploy code.

### Step 14 — Harden documentation and demonstration

Write a clear README, architecture diagram, setup and reset instructions, threat model, failure-mode analysis, trade-off ADRs, and an evaluation methodology. Provide a short recorded or scripted demo that includes one successful run and one deliberate failure/recovery case.

**Exit check:** An engineer unfamiliar with the codebase can reproduce the demo, inspect the evidence, and understand the system's limits.

## 15. Decisions to settle before coding

1. **Demo service language:** Go if the goal is to showcase cross-language backend depth; Python if speed and single-language maintainability matter more.
2. **First two incident scenarios:** Prefer failures with objective signals and small, valid repairs; avoid vague “performance is bad” cases initially.
3. **Model provider:** Choose one with stable structured-output support, then hide it behind an internal interface. Avoid early multi-provider abstractions beyond what tests require.
4. **Sandbox trust model:** Local trusted demo only, or future public users? This changes the isolation design substantially.
5. **Ground-truth definition:** Specify exact root-cause labels, expected evidence, and pass/fail tests before building prompts to avoid benchmark leakage and moving targets.

## 16. Definition of done for the first release

The first release is done when a clean checkout can start the system; two fault scenarios reproduce reliably; a run survives worker interruption; diagnoses cite real evidence; approval gates repair; a patch is checked in a constrained sandbox against before/after replay and regression tests; the UI and report expose all material facts, uncertainty, policy decisions, costs, and artifacts; and a repeatable evaluation command compares the system against baselines. No automatic merge or deployment is present.

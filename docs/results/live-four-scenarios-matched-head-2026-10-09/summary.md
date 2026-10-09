## Live-model results

Measured on 2026-10-09 with `gpt-5.4-mini`, prompts `diagnosis-v2` and `repair-v8`,
against isolated source snapshot `36a20fd72be99e1ebadad1deee620c311dbbe177`.
The current batch runs three trials per scenario with matching Git HEAD evidence.
Every successful repair passed all seven sandbox gates, including replay checks
that preserve the other three inactive faults. Approval is automated by the evaluator.

| Batch / scenario | Attempts | Reproduction | Valid cited diagnosis¹ | Verified repair | Failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current: pool exhaustion | 3 | 3/3 (100.0%) | 2/3 (66.7%) | 2/3 (66.7%) | 1 |
| Current: inventory underflow | 3 | 3/3 (100.0%) | 2/3 (66.7%) | 2/3 (66.7%) | 1 |
| Current: upstream error masking | 3 | 3/3 (100.0%) | 2/3 (66.7%) | 2/3 (66.7%) | 1 |
| Current: mutation response cache | 3 | 3/3 (100.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 3 |
| **Current four-scenario batch** | 12 | 12/12 (100.0%) | 6/12 (50.0%) | 6/12 (50.0%) | 6 |
| Earlier four-scenario snapshot setup | 12 | 12/12 (100.0%) | 6/12 (50.0%) | 6/12 (50.0%) | 6 |
| Original two-scenario model batch | 6 | 6/6 (100.0%) | 5/6 (83.3%) | 5/6 (83.3%) | 1 |
| Earlier authentication failures | 6 | 6/6 (100.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 6 |
| **All recorded attempts** | 36 | 36/36 (100.0%) | 17/36 (47.2%) | 17/36 (47.2%) | 19 |

The current batch has six diagnosis failures: three misused gap evidence and
three exceeded the follow-up or correction-query rules. No repair was generated
for those failures. The earlier four-scenario batch included Git HEAD metadata
gaps caused by the initial snapshot setup; it is retained separately. The
original model and authentication batches are also retained. The combined row
is an audit count across different setups, not a comparable model-accuracy estimate.

¹Citation validity is a **trial success rate**: every citation must resolve,
no gap may support a hypothesis, and cited artifacts must pass SHA-256 checks.
The current batch emitted **44/44 resolving citation IDs**; this measures
integrity, not whether the evidence semantically proves the diagnosis.

See the [current report](../live-four-scenarios-matched-head-2026-10-09/report.json),
[all current failures](../live-four-scenarios-matched-head-2026-10-09/failures.json),
[artifact manifest](../live-four-scenarios-matched-head-2026-10-09/artifact-manifest.json),
[earlier four-scenario report](../live-four-scenarios-2026-10-09/report.json), and
[methodology and historical batches](../../evaluation.md). The
[exact evaluation source archive](../live-four-scenarios-2026-10-09/source.tar.gz)
is preserved for reproduction. This remains a small pilot in one application.


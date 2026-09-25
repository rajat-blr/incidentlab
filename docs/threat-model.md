# Threat model

## Assets and security goals

- Protect developer credentials, source outside the allowlist, Docker access, and
  private evaluation truth.
- Prevent untrusted telemetry or model output from selecting commands, inventing
  valid evidence, bypassing approval, or determining verification outcomes.
- Preserve attribution and integrity from raw artifact to displayed conclusion.
- Prevent the optional GitHub integration from merging or deploying code.

## Adversaries and inputs

Repository text, logs, traces, metrics, HTTP payloads, model responses, candidate
diffs, webhook bodies, and remote API responses are untrusted. The local machine
owner and trusted verifier process are inside the first-release trust boundary.

## Controls

| Threat | Control | Residual risk |
| --- | --- | --- |
| Prompt injection in telemetry | Typed prompts/tools, redaction, citation validation, two-call budget | A model may still form a wrong but schema-valid hypothesis |
| Fabricated evidence | Every citation resolves to a stored non-gap item and immutable artifact hash | Upstream telemetry can itself be misleading |
| Malicious patch | Path/size/content policy, clean apply, fixed sandbox commands | Docker is not a VM boundary against kernel vulnerabilities |
| Secret disclosure | Secret-pattern redaction, bounded artifacts, no sandbox network | Pattern matching cannot identify every secret format |
| Duplicate/retried effects | Stable workflow effect keys, database uniqueness, deterministic GitHub branch and PR lookup | External providers can have temporary read-after-write delay |
| Forged webhook | HMAC-SHA256 over exact body and minimal permission validation | Endpoint availability still depends on tunnel/TLS configuration |
| Supply-chain drift | Locked Python/Node dependencies and pinned container image references | Tags in Compose should be mirrored and digest-pinned for higher assurance |

## Out of scope

This release is a trusted, single-user local lab. It is not a multi-tenant service,
does not execute arbitrary repositories, does not provide VM-grade isolation, and
does not merge or deploy changes. Operator compromise, Docker daemon compromise,
and malicious dependency registries are not solved here.

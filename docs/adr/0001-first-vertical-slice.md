# ADR 0001: First vertical slice

**Status:** Accepted for the local demo, 2026-09-22; provider amended 2026-09-25

## Decisions

- Use Python 3.12+ for the sample service and control plane. This keeps the first incident and the later FastAPI control plane in one language.
- Start with one checkout incident: database pool exhaustion caused by a connection not returned after an out-of-stock request. Use a two-slot pool so the signal is fast and deterministic.
- Use a local SQLite file for the first service fixture. The explicit pool models acquisition and return; it does not claim to emulate every PostgreSQL behavior. The control plane will use PostgreSQL as specified in the PRD.
- Select Gemini as the first model provider behind a typed internal adapter. Its free developer tier and Pydantic-backed structured outputs support the local Step 7 demo without a paid account. Keep the provider transport separate from deterministic schema, citation, tool-policy, and budget validation. Keep prompts and ground truth separate.
- Use Docker Compose for the later local stack. Verification will run in separate constrained workers and fresh workspaces; the API will not receive the Docker socket.

## Scenario contract

The public contract is versioned in `scenarios/pool-exhaustion.public.json`; evaluation truth is in `scenarios/private/pool-exhaustion.truth.json`. The replay sends two out-of-stock requests, then a valid checkout. Under the fault, both pool slots remain occupied and the valid checkout returns `503` with error `database_pool_timeout`. With the fault disabled, both rejected checkouts return `409` and the valid checkout returns `200`. Reset recreates seed inventory before each run. The scenario succeeds only if the failure is observed before diagnosis or repair begins.

The ground-truth label and expected repair are evaluation inputs. Future diagnosis and repair workers must not mount or read `scenarios/private`.

## Trust boundary and deferred scope

This is a trusted, single-user local demo. HTTP input, logs, repository content, and future model output are untrusted data. The eventual model receives typed bounded tools, never a general command runner. Patch creation requires explicit approval; verification applies a diff only in an isolated workspace. No component merges or deploys. Arbitrary repositories, public multi-tenant execution, stronger hostile-code isolation, and GitHub writes are outside this slice.

The service's fault switch is controlled at process startup so a request cannot turn the fault on or off. Its `503` response is a reproduction signal, not evidence of a verified repair. Verification later must prove the baseline fails, the patched service passes repeated replay, and required regression checks pass.

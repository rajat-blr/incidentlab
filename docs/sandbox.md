# Sandbox boundary

The Step 8 verifier is a host-side runner that accepts a full pinned commit and a
bounded unified diff. It is not called from the API or model worker, and those
services do not receive the Docker socket.

For every candidate, the runner:

1. exports fresh baseline and candidate trees with `git archive`;
2. omits `scenarios/private` from both trees;
3. rejects oversized, binary, symlink, rename, traversal, `.git`, private, and
   non-allowlisted patch paths;
4. proves the incident still exists in the unmodified baseline;
5. applies the patch with `git apply --check` and strict whitespace handling;
6. runs fixed build, static, regression, healthy integration, and repeated
   incident-replay commands; and
7. stores bounded logs and SHA-256 hashes before deleting both workspaces.

Each verification container uses:

- a pinned base image and recorded built-image digest;
- an unprivileged numeric user;
- `--network none`, with no host or Docker socket mount;
- a read-only root filesystem and read-only candidate workspace;
- dropped Linux capabilities and `no-new-privileges`;
- CPU, memory, PID, file-descriptor, wall-time, output, and `/tmp` limits; and
- an isolated, size-bounded tmpfs for the only writable filesystem.

This boundary contains the Step 8 hostile probe: it cannot read the Docker socket
or repository metadata, write to the root filesystem or candidate mount, or open
an external network connection. An invalid traversal patch is rejected before a
container starts.

This is a local single-user development boundary, not a hardened environment for
arbitrary hostile multi-tenant workloads. Rootless Docker is preferable when
available. A public service would require stronger isolation such as disposable
microVMs, dedicated workers, egress enforcement outside the container namespace,
and a separate security review.

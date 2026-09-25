"""Build the sandbox and test good, bad, invalid, and contained hostile patches."""

import difflib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incidentlab.sandbox.runner import DockerSandboxRunner, SandboxError

IMAGE = "incidentlab-sandbox:step8"
APP_PATH = "sample_service/app.py"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def patch_for(original: str, modified: str) -> str:
    body = difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{APP_PATH}",
        tofile=f"b/{APP_PATH}",
    )
    return f"diff --git a/{APP_PATH} b/{APP_PATH}\n" + "".join(body)


def repaired(source: str) -> str:
    faulty = """                if row[0] < quantity:
                    if self.fault_mode == "pool_leak":
                        # Intentional incident fixture: this branch leaves its slot checked out.
                        return_connection = False
                    return 409, {"error": "out_of_stock"}
"""
    fixed = """                if row[0] < quantity:
                    return 409, {"error": "out_of_stock"}
"""
    if source.count(faulty) != 1:
        raise AssertionError("Known fault block changed; update the acceptance fixture")
    return source.replace(faulty, fixed)


def hostile_probe(source: str) -> str:
    marker = (
        "from sample_service.telemetry import configure_telemetry, emit_log, "
        "request_id_from_header\n\n\nclass PoolTimeout"
    )
    probe = r"""


def _sandbox_boundary_probe() -> None:
    import socket

    results = {}
    for name, path, operation in (
        ("docker_socket", "/var/run/docker.sock", "read"),
        ("repository_metadata", "/repository/.git/HEAD", "read"),
        ("root_write", "/incidentlab-host-escape", "write"),
        ("workspace_write", "/workspace/incidentlab-host-escape", "write"),
    ):
        try:
            if operation == "read":
                Path(path).read_bytes()
            else:
                Path(path).write_text("escaped")
            results[name] = True
        except OSError:
            results[name] = False
    try:
        connection = socket.create_connection(("1.1.1.1", 53), timeout=0.25)
        connection.close()
        results["external_network"] = True
    except OSError:
        results["external_network"] = False
    print("SANDBOX_PROBE=" + json.dumps(results, sort_keys=True), flush=True)


_sandbox_boundary_probe()
"""
    if source.count(marker) != 1:
        raise AssertionError("Probe insertion point changed")
    replacement = marker.removesuffix("\n\n\nclass PoolTimeout") + probe + "\n\nclass PoolTimeout"
    return source.replace(marker, replacement, 1)


def read_artifacts(result) -> str:
    return "\n".join(
        Path(check.artifact_ref).read_text(errors="replace") for check in result.checks
    )


def main() -> None:
    subprocess.run(
        ["docker", "build", "-f", "Dockerfile.sandbox", "-t", IMAGE, "."],
        check=True,
    )
    commit = git("rev-parse", "HEAD").strip()
    source = git("show", f"{commit}:{APP_PATH}")
    with tempfile.TemporaryDirectory(prefix="incidentlab-step8-artifacts-") as temporary:
        runner = DockerSandboxRunner(Path.cwd(), Path(temporary), image=IMAGE)

        good = runner.run(commit, patch_for(source, repaired(source)))
        if good.outcome != "PASS" or not good.cleanup_succeeded:
            raise AssertionError(f"Known-good patch did not pass: {good}")

        broken = repaired(source).replace(
            'return 409, {"error": "out_of_stock"}', "return this is not valid python", 1
        )
        bad = runner.run(commit, patch_for(source, broken))
        if bad.outcome != "FAIL" or bad.checks[-1].name != "build":
            raise AssertionError(f"Known-bad patch was not rejected by build: {bad}")

        malicious_source = hostile_probe(repaired(source))
        hostile = runner.run(commit, patch_for(source, malicious_source))
        output = read_artifacts(hostile)
        expected_probe = (
            'SANDBOX_PROBE={"docker_socket": false, "external_network": false, '
            '"repository_metadata": false, "root_write": false, "workspace_write": false}'
        )
        if hostile.outcome != "PASS" or expected_probe not in output:
            probe_lines = [line for line in output.splitlines() if "SANDBOX_PROBE=" in line]
            raise AssertionError(
                f"Hostile probe containment mismatch: outcome={hostile.outcome}, "
                f"probes={probe_lines}, last_check={hostile.checks[-1]}, "
                f"last_output={Path(hostile.checks[-1].artifact_ref).read_text(errors='replace')}"
            )
        if Path("/incidentlab-host-escape").exists():
            raise AssertionError("Hostile patch wrote outside its workspace")

        invalid = """diff --git a/../../.env b/../../.env
--- a/../../.env
+++ b/../../.env
@@ -0,0 +1 @@
+escaped=true
"""
        try:
            runner.run(commit, invalid)
        except SandboxError as error:
            invalid_rejection = str(error)
        else:
            raise AssertionError("Unsafe patch path was accepted")

        print(
            json.dumps(
                {
                    "target_commit": commit,
                    "environment_digest": good.environment_digest,
                    "good_outcome": good.outcome,
                    "good_checks": [check.name for check in good.checks],
                    "bad_outcome": bad.outcome,
                    "bad_rejected_at": bad.checks[-1].name,
                    "hostile_outcome": hostile.outcome,
                    "hostile_boundaries_contained": True,
                    "invalid_patch_rejection": invalid_rejection,
                    "artifacts_hashed": all(
                        len(check.content_sha256) == 64
                        for result in (good, bad, hostile)
                        for check in result.checks
                    ),
                    "cleanup_succeeded": all(
                        result.cleanup_succeeded for result in (good, bad, hostile)
                    ),
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()

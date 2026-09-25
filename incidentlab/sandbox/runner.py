"""Run fixed verification commands against a manual patch in constrained Docker."""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIFF_HEADER_PATTERN = re.compile(r"^diff --git a/(.+) b/(.+)$")


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: int = 30
    max_output_bytes: int = 64 * 1024
    max_patch_bytes: int = 64 * 1024
    max_changed_files: int = 8
    cpus: str = "1.0"
    memory: str = "512m"
    pids: int = 128
    tmpfs_bytes: int = 64 * 1024 * 1024


@dataclass(frozen=True)
class SandboxCheckResult:
    name: str
    outcome: str
    started_at: str
    finished_at: str
    exit_code: int | None
    failure_reason: str | None
    artifact_ref: str
    content_sha256: str


@dataclass(frozen=True)
class SandboxRunResult:
    candidate_id: str
    target_commit: str
    environment_digest: str
    changed_paths: tuple[str, ...]
    checks: tuple[SandboxCheckResult, ...]
    outcome: str
    artifacts_dir: str
    cleanup_succeeded: bool


@dataclass(frozen=True)
class _Execution:
    exit_code: int | None
    output: bytes
    failure_reason: str | None


class SandboxError(RuntimeError):
    """Raised when the trusted runner cannot establish its safety boundary."""


class DockerSandboxRunner:
    """A host-side runner. It is intentionally separate from API/model workers."""

    def __init__(
        self,
        repository: Path,
        artifacts_root: Path,
        *,
        image: str = "incidentlab-sandbox:step8",
        allowed_path_prefixes: tuple[str, ...] = ("sample_service/",),
        limits: SandboxLimits | None = None,
    ) -> None:
        self.repository = repository.resolve()
        self.artifacts_root = artifacts_root.resolve()
        self.image = image
        self.allowed_path_prefixes = allowed_path_prefixes
        self.limits = limits or SandboxLimits()

    def image_digest(self) -> str:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", self.image],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        digest = result.stdout.strip()
        if result.returncode or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise SandboxError(f"sandbox image is unavailable: {self.image}")
        return digest

    def _validate_commit(self, commit: str) -> None:
        if not COMMIT_PATTERN.fullmatch(commit):
            raise SandboxError("target commit must be a full lowercase SHA-1")
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=self.repository,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode:
            raise SandboxError("target commit does not exist in the repository")

    def _validate_patch(self, unified_diff: str) -> tuple[str, ...]:
        encoded = unified_diff.encode("utf-8")
        if not encoded or len(encoded) > self.limits.max_patch_bytes:
            raise SandboxError("patch is empty or exceeds the byte limit")
        if "\x00" in unified_diff or "GIT binary patch" in unified_diff:
            raise SandboxError("binary patches are not allowed")
        if "new file mode 120000" in unified_diff or "old mode 120000" in unified_diff:
            raise SandboxError("symbolic-link patches are not allowed")

        paths: list[str] = []
        for line in unified_diff.splitlines():
            match = DIFF_HEADER_PATTERN.fullmatch(line)
            if not match:
                continue
            old_path, new_path = match.groups()
            if old_path != new_path:
                raise SandboxError("renames are not allowed")
            path = PurePosixPath(new_path)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
                raise SandboxError("patch contains an unsafe path")
            normalized = path.as_posix()
            if normalized.startswith("scenarios/private/"):
                raise SandboxError("private evaluation inputs cannot be patched")
            if not any(normalized.startswith(prefix) for prefix in self.allowed_path_prefixes):
                raise SandboxError(f"patch path is outside the allowlist: {normalized}")
            if normalized not in paths:
                paths.append(normalized)
        if not paths:
            raise SandboxError("patch contains no file diff")
        if len(paths) > self.limits.max_changed_files:
            raise SandboxError("patch changes too many files")
        return tuple(paths)

    def _export_commit(self, commit: str, destination: Path) -> None:
        result = subprocess.run(
            ["git", "archive", "--format=tar", commit],
            cwd=self.repository,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise SandboxError("could not export the pinned commit")
        total_size = 0
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise SandboxError("repository archive contains an unsafe path")
                if relative.parts[:2] == ("scenarios", "private"):
                    continue
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise SandboxError("repository archive contains a non-regular file")
                total_size += member.size
                if total_size > 32 * 1024 * 1024:
                    raise SandboxError("repository archive exceeds the size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise SandboxError("repository archive member could not be read")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read())
                target.chmod(member.mode & 0o777)

    def _apply_patch(self, workspace: Path, unified_diff: str) -> _Execution:
        started = time.monotonic()
        commands = (
            ["git", "apply", "--check", "--whitespace=error-all", "-"],
            ["git", "apply", "--whitespace=error-all", "-"],
        )
        output = bytearray()
        for command in commands:
            remaining = max(1, self.limits.timeout_seconds - int(time.monotonic() - started))
            try:
                result = subprocess.run(
                    command,
                    cwd=workspace,
                    input=unified_diff,
                    capture_output=True,
                    text=True,
                    timeout=remaining,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return _Execution(None, bytes(output), "timeout")
            output.extend(result.stdout.encode())
            output.extend(result.stderr.encode())
            if len(output) > self.limits.max_output_bytes:
                bounded = bytes(output[: self.limits.max_output_bytes])
                return _Execution(None, bounded, "output_limit")
            if result.returncode:
                return _Execution(result.returncode, bytes(output), "patch_rejected")
        if any(path.is_symlink() for path in workspace.rglob("*")):
            return _Execution(None, bytes(output), "symlink_created")
        return _Execution(0, bytes(output), None)

    def _container_command(self, name: str, workspace: Path, command: tuple[str, ...]) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.limits.pids),
            "--memory",
            self.limits.memory,
            "--memory-swap",
            self.limits.memory,
            "--cpus",
            self.limits.cpus,
            "--ulimit",
            "nofile=256:256",
            "--user",
            "65532:65532",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={self.limits.tmpfs_bytes},mode=1777",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace,readonly",
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp/home",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONPYCACHEPREFIX=/tmp/pycache",
            self.image,
            *command,
        ]

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    @staticmethod
    def _force_remove(container_name: str) -> None:
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            capture_output=True,
            timeout=10,
            check=False,
        )

    def _execute_container(
        self,
        workspace: Path,
        command: tuple[str, ...],
        cancel_event: threading.Event | None,
    ) -> _Execution:
        container_name = f"incidentlab-sandbox-{uuid.uuid4().hex[:16]}"
        process = subprocess.Popen(
            self._container_command(container_name, workspace, command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        output = bytearray()
        output_limit = threading.Event()

        def read_output() -> None:
            while chunk := process.stdout.read(8192):
                remaining = self.limits.max_output_bytes - len(output)
                output.extend(chunk[: max(0, remaining)])
                if len(chunk) > remaining:
                    output_limit.set()
                    return

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = time.monotonic() + self.limits.timeout_seconds
        failure_reason = None
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                failure_reason = "cancelled"
                break
            if output_limit.is_set():
                failure_reason = "output_limit"
                break
            if time.monotonic() >= deadline:
                failure_reason = "timeout"
                break
            time.sleep(0.05)
        if failure_reason:
            self._terminate(process)
            self._force_remove(container_name)
        reader.join(timeout=2)
        exit_code = process.poll()
        if failure_reason in {"timeout", "cancelled", "output_limit"}:
            exit_code = None
        elif exit_code:
            failure_reason = "command_failed"
        return _Execution(exit_code, bytes(output), failure_reason)

    def _record_check(
        self,
        artifacts_dir: Path,
        index: int,
        name: str,
        execution: _Execution,
        started: datetime,
    ) -> SandboxCheckResult:
        finished = datetime.now(UTC)
        outcome = "PASS" if execution.exit_code == 0 and not execution.failure_reason else "FAIL"
        if execution.failure_reason in {"cancelled", "timeout", "output_limit"}:
            outcome = "INCONCLUSIVE"
        header = json.dumps(
            {
                "name": name,
                "outcome": outcome,
                "exit_code": execution.exit_code,
                "failure_reason": execution.failure_reason,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
            },
            sort_keys=True,
        ).encode()
        content = header + b"\n" + execution.output
        artifact = artifacts_dir / f"{index:02d}-{name}.log"
        artifact.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        return SandboxCheckResult(
            name=name,
            outcome=outcome,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            exit_code=execution.exit_code,
            failure_reason=execution.failure_reason,
            artifact_ref=str(artifact),
            content_sha256=digest,
        )

    def run(
        self,
        target_commit: str,
        unified_diff: str,
        *,
        candidate_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SandboxRunResult:
        self._validate_commit(target_commit)
        changed_paths = self._validate_patch(unified_diff)
        environment_digest = self.image_digest()
        identifier = str(uuid.UUID(candidate_id)) if candidate_id else str(uuid.uuid4())
        artifacts_dir = self.artifacts_root / identifier
        artifacts_dir.mkdir(parents=True, exist_ok=False)
        checks: list[SandboxCheckResult] = []
        cleanup_succeeded = False

        fixed_checks: tuple[tuple[str, tuple[str, ...]], ...] = (
            (
                "build",
                (
                    "python",
                    "-m",
                    "compileall",
                    "-q",
                    "sample_service",
                    "incidentlab",
                    "tests",
                ),
            ),
            ("static", ("ruff", "check", "--no-cache", "sample_service")),
            (
                "unit",
                (
                    "python",
                    "-m",
                    "unittest",
                    "tests.test_sample_service.CheckoutIncidentTests.test_valid_checkout_and_unknown_sku_return_connections",
                    "-v",
                ),
            ),
            (
                "integration",
                (
                    "python",
                    "/opt/incidentlab-runner/container_check.py",
                    "healthy",
                    "--trials",
                    "3",
                ),
            ),
            (
                "incident_replay",
                (
                    "python",
                    "/opt/incidentlab-runner/container_check.py",
                    "repaired",
                    "--trials",
                    "5",
                ),
            ),
        )

        try:
            with tempfile.TemporaryDirectory(prefix="incidentlab-sandbox-") as temporary:
                root = Path(temporary)
                baseline = root / "baseline"
                candidate = root / "candidate"
                baseline.mkdir()
                candidate.mkdir()
                self._export_commit(target_commit, baseline)
                self._export_commit(target_commit, candidate)

                started = datetime.now(UTC)
                execution = self._execute_container(
                    baseline,
                    (
                        "python",
                        "/opt/incidentlab-runner/container_check.py",
                        "baseline",
                        "--trials",
                        "3",
                    ),
                    cancel_event,
                )
                checks.append(
                    self._record_check(
                        artifacts_dir, len(checks), "baseline_replay", execution, started
                    )
                )
                if checks[-1].outcome != "PASS":
                    outcome = "INCONCLUSIVE"
                else:
                    started = datetime.now(UTC)
                    execution = self._apply_patch(candidate, unified_diff)
                    checks.append(
                        self._record_check(
                            artifacts_dir, len(checks), "patch_apply", execution, started
                        )
                    )
                    outcome = "PASS" if checks[-1].outcome == "PASS" else "FAIL"
                    if outcome == "PASS":
                        for check_name, command in fixed_checks:
                            started = datetime.now(UTC)
                            execution = self._execute_container(candidate, command, cancel_event)
                            checks.append(
                                self._record_check(
                                    artifacts_dir,
                                    len(checks),
                                    check_name,
                                    execution,
                                    started,
                                )
                            )
                            if checks[-1].outcome != "PASS":
                                outcome = (
                                    "INCONCLUSIVE"
                                    if checks[-1].outcome == "INCONCLUSIVE"
                                    else "FAIL"
                                )
                                break
                cleanup_succeeded = True
        finally:
            manifest = {
                "candidate_id": identifier,
                "target_commit": target_commit,
                "environment_digest": environment_digest,
                "changed_paths": list(changed_paths),
                "checks": [asdict(check) for check in checks],
                "outcome": locals().get("outcome", "INCONCLUSIVE"),
                "cleanup_succeeded": cleanup_succeeded,
            }
            manifest_path = artifacts_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        return SandboxRunResult(
            candidate_id=identifier,
            target_commit=target_commit,
            environment_digest=environment_digest,
            changed_paths=changed_paths,
            checks=tuple(checks),
            outcome=outcome,
            artifacts_dir=str(artifacts_dir),
            cleanup_succeeded=cleanup_succeeded,
        )

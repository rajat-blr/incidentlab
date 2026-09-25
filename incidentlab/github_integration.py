"""Opt-in, draft-only GitHub boundary with fail-closed validation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from incidentlab.contracts.models import IncidentRun, RepairCandidate, VerificationRun

REQUIRED_PERMISSIONS = {
    "metadata": "read",
    "contents": "write",
    "pull_requests": "write",
}
FORBIDDEN_WRITE_PERMISSIONS = {"administration", "deployments", "workflows"}


class GitHubIntegrationError(RuntimeError):
    pass


def verify_webhook_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def validate_installation_permissions(permissions: dict[str, str]) -> None:
    missing = {
        name: level
        for name, level in REQUIRED_PERMISSIONS.items()
        if permissions.get(name) != level
    }
    forbidden = sorted(
        name for name in FORBIDDEN_WRITE_PERMISSIONS if permissions.get(name) in {"write", "admin"}
    )
    if missing or forbidden:
        raise GitHubIntegrationError(
            f"unsafe GitHub App permissions: missing={missing}, forbidden={forbidden}"
        )


class DraftPullRequestClient(Protocol):
    def find_pull_request(self, branch: str) -> dict | None: ...

    def ensure_candidate_branch(self, branch: str, base_sha: str, unified_diff: str) -> None: ...

    def create_draft_pull_request(
        self, branch: str, base_branch: str, title: str, body: str
    ) -> dict: ...


@dataclass(frozen=True)
class DraftPullRequestResult:
    number: int
    url: str
    branch: str
    created: bool
    draft: bool


def create_or_get_draft_pull_request(
    client: DraftPullRequestClient,
    run: IncidentRun,
    candidate: RepairCandidate,
    verification: VerificationRun,
    report_url: str,
    *,
    base_branch: str = "main",
) -> DraftPullRequestResult:
    if candidate.run_id != run.id or verification.candidate_id != candidate.id:
        raise GitHubIntegrationError("run, candidate, and verification do not match")
    if verification.outcome != "PASS":
        raise GitHubIntegrationError("only a verified candidate can become a draft PR")
    branch = f"incidentlab/run-{run.id}"
    existing = client.find_pull_request(branch)
    if existing is not None:
        if not existing.get("draft", False):
            raise GitHubIntegrationError("existing pull request is not a draft")
        return DraftPullRequestResult(
            number=int(existing["number"]),
            url=str(existing["html_url"]),
            branch=branch,
            created=False,
            draft=True,
        )
    client.ensure_candidate_branch(branch, run.pinned_commit, candidate.unified_diff)
    created = client.create_draft_pull_request(
        branch,
        base_branch,
        f"IncidentLab: {candidate.explanation[:120]}",
        "\n".join(
            [
                "This draft was created after deterministic sandbox verification.",
                "",
                f"- IncidentLab run: `{run.id}`",
                f"- Verification: **{verification.outcome}**, "
                f"rank {verification.rank or 'unranked'}",
                f"- Candidate SHA-256: `{candidate.diff_sha256}`",
                f"- Review report: {report_url}",
                "",
                "IncidentLab cannot mark this PR ready, merge it, or deploy it.",
            ]
        ),
    )
    if not created.get("draft", False):
        raise GitHubIntegrationError("GitHub did not create a draft pull request")
    return DraftPullRequestResult(
        number=int(created["number"]),
        url=str(created["html_url"]),
        branch=branch,
        created=True,
        draft=True,
    )


class GitHubRestClient:
    """Small REST adapter; intentionally exposes no merge or deployment operation."""

    def __init__(self, repository: str, token: str, local_repository: Path) -> None:
        if not token:
            raise GitHubIntegrationError("GITHUB_INSTALLATION_TOKEN is required")
        owner, separator, name = repository.partition("/")
        if not separator or not owner or not name:
            raise GitHubIntegrationError("repository must be owner/name")
        self.repository = repository
        self.owner = owner
        self.token = token
        self.local_repository = local_repository.resolve()

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read(4096).decode(errors="replace")
            raise GitHubIntegrationError(f"GitHub API {error.code}: {detail}") from error

    def _optional_request(self, path: str) -> dict | list | None:
        try:
            return self._request("GET", path)
        except GitHubIntegrationError as error:
            if "GitHub API 404:" in str(error):
                return None
            raise

    def find_pull_request(self, branch: str) -> dict | None:
        query = urllib.parse.urlencode({"state": "all", "head": f"{self.owner}:{branch}"})
        result = self._request("GET", f"/pulls?{query}")
        return result[0] if isinstance(result, list) and result else None

    @staticmethod
    def _changed_paths(unified_diff: str) -> tuple[str, ...]:
        paths = []
        for line in unified_diff.splitlines():
            if line.startswith("diff --git a/") and " b/" in line:
                old_path, new_path = line.removeprefix("diff --git a/").split(" b/", 1)
                if old_path != new_path or ".." in Path(new_path).parts:
                    raise GitHubIntegrationError("draft PR diff contains an unsafe path")
                paths.append(new_path)
        if not paths:
            raise GitHubIntegrationError("draft PR diff contains no changed path")
        return tuple(dict.fromkeys(paths))

    def ensure_candidate_branch(self, branch: str, base_sha: str, unified_diff: str) -> None:
        encoded_branch = urllib.parse.quote(branch, safe="")
        if self._optional_request(f"/git/ref/heads/{encoded_branch}") is None:
            self._request("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": base_sha})
        paths = self._changed_paths(unified_diff)
        with tempfile.TemporaryDirectory(prefix="incidentlab-github-") as temporary:
            workspace = Path(temporary)
            archive = subprocess.run(
                ["git", "archive", base_sha],
                cwd=self.local_repository,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["tar", "-xf", "-", "-C", str(workspace)],
                input=archive.stdout,
                check=True,
            )
            subprocess.run(
                ["git", "apply", "--check", "-"],
                cwd=workspace,
                input=unified_diff.encode(),
                check=True,
            )
            subprocess.run(
                ["git", "apply", "-"],
                cwd=workspace,
                input=unified_diff.encode(),
                check=True,
            )
            for path in paths:
                encoded_path = urllib.parse.quote(path, safe="/")
                current = self._request("GET", f"/contents/{encoded_path}?ref={encoded_branch}")
                if not isinstance(current, dict) or "sha" not in current:
                    raise GitHubIntegrationError(f"could not read branch file: {path}")
                content = (workspace / path).read_bytes()
                remote = base64.b64decode(str(current.get("content", "")), validate=False)
                if remote == content:
                    continue
                self._request(
                    "PUT",
                    f"/contents/{encoded_path}",
                    {
                        "message": f"Apply verified IncidentLab repair ({base_sha[:12]})",
                        "content": base64.b64encode(content).decode(),
                        "sha": current["sha"],
                        "branch": branch,
                    },
                )

    def create_draft_pull_request(
        self, branch: str, base_branch: str, title: str, body: str
    ) -> dict:
        result = self._request(
            "POST",
            "/pulls",
            {"title": title, "head": branch, "base": base_branch, "body": body, "draft": True},
        )
        if not isinstance(result, dict):
            raise GitHubIntegrationError("unexpected GitHub pull request response")
        return result

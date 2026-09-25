"""Deterministic validation and in-memory application of model-proposed diffs."""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from incidentlab.contracts.models import RepairCandidateDraft

POLICY_VERSION = "repair-policy-v1"
DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")
SECRET_PATTERNS = (
    re.compile(r"AQ\.[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|password|secret|token)\s*=\s*['\"][^'\"]{8,}['\"]"),
)
FORBIDDEN_ADDITIONS = (
    re.compile(r"\b(?:eval|exec|compile)\s*\("),
    re.compile(r"\b(?:os\.system|subprocess\.|socket\.|requests\.)"),
    re.compile(r"\burllib\.(?:request|parse)"),
    re.compile(r"/var/run/docker\.sock"),
)


class PolicyViolation(ValueError):
    def __init__(self, category: str, detail: str):
        super().__init__(detail)
        self.category = category
        self.detail = detail


@dataclass(frozen=True)
class PolicyDecision:
    accepted: bool
    category: str
    detail: str
    changed_paths: tuple[str, ...]
    diff_sha256: str
    patched_source: str | None = None


@dataclass(frozen=True)
class _ParsedDiff:
    path: str
    hunks: tuple[tuple[int, int, int, int, tuple[str, ...]], ...]
    added_lines: tuple[str, ...]
    changed_line_count: int


class RepairPolicy:
    def __init__(
        self,
        *,
        allowed_paths: tuple[str, ...] = ("sample_service/app.py",),
        max_patch_bytes: int = 16 * 1024,
        max_changed_lines: int = 80,
    ) -> None:
        self.allowed_paths = allowed_paths
        self.max_patch_bytes = max_patch_bytes
        self.max_changed_lines = max_changed_lines

    @staticmethod
    def _safe_path(value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
            raise PolicyViolation("unsafe_path", "diff contains an unsafe path")
        return path.as_posix()

    def _parse(self, unified_diff: str) -> _ParsedDiff:
        encoded = unified_diff.encode("utf-8")
        if not encoded or len(encoded) > self.max_patch_bytes:
            raise PolicyViolation("patch_size", "diff is empty or exceeds the byte limit")
        if "\x00" in unified_diff or "GIT binary patch" in unified_diff:
            raise PolicyViolation("binary_patch", "binary patches are forbidden")
        if "new file mode" in unified_diff or "deleted file mode" in unified_diff:
            raise PolicyViolation("file_operation", "file creation and deletion are forbidden")
        if "old mode" in unified_diff or "new mode" in unified_diff:
            raise PolicyViolation("file_mode", "file-mode changes are forbidden")

        lines = unified_diff.splitlines(keepends=True)
        index = 0
        paths: list[str] = []
        hunks: list[tuple[int, int, int, int, tuple[str, ...]]] = []
        additions: list[str] = []
        changed = 0
        while index < len(lines):
            line = lines[index]
            header = DIFF_HEADER.fullmatch(line.rstrip("\n"))
            if header:
                old_path = self._safe_path(header.group(1))
                new_path = self._safe_path(header.group(2))
                if old_path != new_path:
                    raise PolicyViolation("rename", "renames are forbidden")
                paths.append(new_path)
                index += 1
                if index + 1 >= len(lines):
                    raise PolicyViolation("malformed_diff", "diff lacks file headers")
                if lines[index].rstrip("\n") != f"--- a/{new_path}":
                    raise PolicyViolation("malformed_diff", "old file header is invalid")
                if lines[index + 1].rstrip("\n") != f"+++ b/{new_path}":
                    raise PolicyViolation("malformed_diff", "new file header is invalid")
                index += 2
                continue
            match = HUNK_HEADER.fullmatch(line.rstrip("\n"))
            if match:
                old_start = int(match.group(1))
                old_count = int(match.group(2) or 1)
                new_start = int(match.group(3))
                new_count = int(match.group(4) or 1)
                index += 1
                body: list[str] = []
                while index < len(lines) and not lines[index].startswith(("@@ ", "diff --git ")):
                    item = lines[index]
                    if item.startswith("\\ No newline at end of file"):
                        index += 1
                        continue
                    if not item.startswith((" ", "+", "-")):
                        raise PolicyViolation("malformed_diff", "hunk contains an invalid line")
                    body.append(item)
                    if item.startswith("+"):
                        additions.append(item[1:].rstrip("\n"))
                        changed += 1
                    elif item.startswith("-"):
                        changed += 1
                    index += 1
                hunks.append((old_start, old_count, new_start, new_count, tuple(body)))
                continue
            if line.strip():
                raise PolicyViolation("malformed_diff", "diff contains unexpected content")
            index += 1

        unique_paths = tuple(dict.fromkeys(paths))
        if len(unique_paths) != 1 or unique_paths[0] not in self.allowed_paths:
            raise PolicyViolation(
                "forbidden_path",
                f"diff must change exactly one allowlisted file: {', '.join(self.allowed_paths)}",
            )
        if not hunks:
            raise PolicyViolation("malformed_diff", "diff contains no hunks")
        if changed > self.max_changed_lines:
            raise PolicyViolation("changed_lines", "diff changes too many lines")
        return _ParsedDiff(unique_paths[0], tuple(hunks), tuple(additions), changed)

    @staticmethod
    def _apply(source: str, parsed: _ParsedDiff, unified_diff: str) -> str:
        """Apply a parsed diff with Git's canonical patch semantics in isolation."""
        with tempfile.TemporaryDirectory(prefix="incidentlab-repair-policy-") as temp_dir:
            root = Path(temp_dir)
            target = root / parsed.path
            target.parent.mkdir(parents=True)
            target.write_text(source, encoding="utf-8")

            command = ["git", "apply", "--whitespace=error-all", "-"]
            check = subprocess.run(
                [*command[:2], "--check", *command[2:]],
                cwd=root,
                input=unified_diff,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            if check.returncode != 0:
                raise PolicyViolation(
                    "patch_apply", "diff does not apply cleanly to the pinned source"
                )
            applied = subprocess.run(
                command,
                cwd=root,
                input=unified_diff,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            if applied.returncode != 0:
                raise PolicyViolation("patch_apply", "diff could not be applied safely")

            files = tuple(
                path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
            )
            if files != (parsed.path,) or target.is_symlink():
                raise PolicyViolation("file_operation", "diff changed an unexpected file")
            return target.read_text(encoding="utf-8")

    def evaluate(self, draft: RepairCandidateDraft, pinned_source: str) -> PolicyDecision:
        digest = hashlib.sha256(draft.unified_diff.encode()).hexdigest()
        try:
            parsed = self._parse(draft.unified_diff)
            added = "\n".join(parsed.added_lines)
            if any(pattern.search(added) for pattern in SECRET_PATTERNS):
                raise PolicyViolation("secret", "diff appears to contain a credential or secret")
            if any(pattern.search(added) for pattern in FORBIDDEN_ADDITIONS):
                raise PolicyViolation("unsafe_code", "diff adds a forbidden execution primitive")
            patched = self._apply(pinned_source, parsed, draft.unified_diff)
            try:
                ast.parse(patched, filename=parsed.path)
            except SyntaxError as error:
                detail = f"patched Python is invalid: {error.msg}"
                raise PolicyViolation("syntax", detail) from error
        except PolicyViolation as error:
            return PolicyDecision(False, error.category, error.detail, (), digest)
        return PolicyDecision(
            True,
            "accepted",
            "diff passed deterministic repair policy",
            (parsed.path,),
            digest,
            patched,
        )

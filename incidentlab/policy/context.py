"""Read bounded repository context from an exact pinned Git object."""

import os
import re
import subprocess
from pathlib import Path, PurePosixPath

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_CONTEXT_PATHS = ("sample_service/app.py",)


class RepositoryContextError(RuntimeError):
    pass


def read_pinned_source(git_dir: Path, commit: str, path: str) -> str:
    if not COMMIT_PATTERN.fullmatch(commit):
        raise RepositoryContextError("invalid pinned commit")
    normalized = PurePosixPath(path).as_posix()
    if normalized not in ALLOWED_CONTEXT_PATHS:
        raise RepositoryContextError("repository path is not allowlisted")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
    }
    try:
        result = subprocess.run(
            ["git", f"--git-dir={git_dir}", "cat-file", "blob", f"{commit}:{normalized}"],
            capture_output=True,
            timeout=10,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RepositoryContextError("could not read pinned repository context") from error
    if result.returncode:
        raise RepositoryContextError("pinned repository context does not exist")
    if len(result.stdout) > 32 * 1024:
        raise RepositoryContextError("pinned repository context exceeds the byte limit")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RepositoryContextError("pinned repository context is not UTF-8") from error

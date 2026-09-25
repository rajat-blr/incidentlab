import subprocess
import tempfile
import unittest
from pathlib import Path

from incidentlab.sandbox.runner import DockerSandboxRunner, SandboxError, SandboxLimits


class SandboxRunnerTests(unittest.TestCase):
    def runner(self, root: Path) -> DockerSandboxRunner:
        return DockerSandboxRunner(
            Path.cwd(),
            root / "artifacts",
            limits=SandboxLimits(timeout_seconds=5),
        )

    def test_patch_paths_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.runner(Path(temporary))
            patch = """diff --git a/sample_service/app.py b/sample_service/app.py
--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -1 +1 @@
-old
+new
"""
            self.assertEqual(runner._validate_patch(patch), ("sample_service/app.py",))

    def test_patch_rejects_paths_outside_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.runner(Path(temporary))
            patch = """diff --git a/../../.env b/../../.env
--- a/../../.env
+++ b/../../.env
@@ -0,0 +1 @@
+stolen=true
"""
            with self.assertRaisesRegex(SandboxError, "unsafe path"):
                runner._validate_patch(patch)

    def test_unknown_scenario_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.runner(Path(temporary))
            with self.assertRaisesRegex(SandboxError, "unsupported verification scenario"):
                runner.run("a" * 40, "unused", scenario_id="unknown")

    def test_export_omits_private_evaluation_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self.runner(root)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            workspace = root / "workspace"
            workspace.mkdir()
            runner._export_commit(commit, workspace)
            self.assertTrue((workspace / "scenarios/pool-exhaustion.public.json").is_file())
            self.assertFalse((workspace / "scenarios/private").exists())

    def test_container_command_enforces_isolation_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self.runner(root)
            command = runner._container_command("test-container", root, ("python", "-V"))
            rendered = " ".join(command)
            self.assertIn("--network none", rendered)
            self.assertIn("--read-only", command)
            self.assertIn("--cap-drop ALL", rendered)
            self.assertIn("no-new-privileges", command)
            self.assertIn("readonly", rendered)
            self.assertNotIn("docker.sock", rendered)


if __name__ == "__main__":
    unittest.main()

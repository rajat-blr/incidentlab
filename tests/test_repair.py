import difflib
import hashlib
import json
import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from incidentlab.contracts.models import (
    Hypothesis,
    RepairCandidateDraft,
    RepairGenerationDraft,
)
from incidentlab.model_adapter.diagnosis import Usage
from incidentlab.model_adapter.gemini_repair_adapter import (
    GeminiRepairAdapter,
    GeminiRepairCandidate,
    GeminiRepairSchema,
)
from incidentlab.model_adapter.repair import RepairError, RepairModelResult, generate_repairs
from incidentlab.policy.context import read_pinned_source
from incidentlab.policy.repair import POLICY_VERSION, RepairPolicy

APP_PATH = "sample_service/app.py"


def unified_diff(source: str, modified: str, path: str = APP_PATH) -> str:
    body = difflib.unified_diff(
        source.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return f"diff --git a/{path} b/{path}\n" + "".join(body)


def hypothesis(run_id) -> Hypothesis:
    return Hypothesis(
        id=uuid4(),
        run_id=run_id,
        summary="Leaked database connections",
        mechanism="The out-of-stock path fails to release a checked-out connection.",
        supporting_evidence_ids=["ev-1"],
        contradicting_evidence_ids=[],
        confidence="high",
        model_id="test-model",
        prompt_version="diagnosis-v1",
    )


class FakeRepairAdapter:
    provider = "fake"
    model_id = "fake-repair-model"

    def __init__(self, draft):
        self.draft = draft
        self.payload = None

    def generate(self, payload):
        self.payload = payload
        return RepairModelResult(self.draft, Usage(20, 10, 1))


class SequenceRepairAdapter(FakeRepairAdapter):
    def __init__(self, drafts):
        self.drafts = iter(drafts)
        self.payloads = []

    def generate(self, payload):
        self.payloads.append(payload)
        return RepairModelResult(next(self.drafts), Usage(20, 10, 1))


class RepairPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = Path(APP_PATH).read_text()
        self.fixed = self.source.replace(
            """                    if self.fault_mode == "pool_leak":
                        # Intentional incident fixture: this branch leaves its slot checked out.
                        return_connection = False
""",
            "",
            1,
        )
        self.policy = RepairPolicy()

    def draft(self, diff: str) -> RepairCandidateDraft:
        return RepairCandidateDraft(
            unified_diff=diff,
            explanation="Always release the acquired connection.",
            expected_behavior="The third request succeeds after two rejected requests.",
        )

    def test_valid_diff_applies_to_exact_pinned_source(self) -> None:
        diff = unified_diff(self.source, self.fixed)
        decision = self.policy.evaluate(self.draft(diff), self.source)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.patched_source, self.fixed)
        self.assertEqual(decision.changed_paths, (APP_PATH,))
        self.assertEqual(decision.diff_sha256, hashlib.sha256(diff.encode()).hexdigest())

    def test_forbidden_path_is_rejected(self) -> None:
        diff = unified_diff("old\n", "new\n", "compose.yaml")
        decision = self.policy.evaluate(self.draft(diff), "old\n")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.category, "forbidden_path")

    def test_malformed_context_is_rejected(self) -> None:
        diff = unified_diff(self.source, self.fixed).replace("return_connection = False", "missing")
        decision = self.policy.evaluate(self.draft(diff), self.source)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.category, "patch_apply")

    def test_secret_and_execution_primitives_are_rejected(self) -> None:
        secret_source = self.source.replace(
            "class PoolTimeout(Exception):",
            'API_KEY = "AIza123456789012345678901234567890"\n\nclass PoolTimeout(Exception):',
        )
        secret = self.policy.evaluate(
            self.draft(unified_diff(self.source, secret_source)), self.source
        )
        self.assertEqual(secret.category, "secret")

        unsafe_source = self.source.replace(
            "class PoolTimeout(Exception):",
            'eval("1 + 1")\n\nclass PoolTimeout(Exception):',
        )
        unsafe = self.policy.evaluate(
            self.draft(unified_diff(self.source, unsafe_source)), self.source
        )
        self.assertEqual(unsafe.category, "unsafe_code")


class RepairGenerationTests(unittest.TestCase):
    def test_only_policy_accepted_candidates_are_returned(self) -> None:
        source = Path(APP_PATH).read_text()
        fixed = source.replace(
            """                    if self.fault_mode == "pool_leak":
                        # Intentional incident fixture: this branch leaves its slot checked out.
                        return_connection = False
""",
            "",
            1,
        )
        valid = RepairCandidateDraft(
            unified_diff=unified_diff(source, fixed),
            explanation="Release the connection.",
            expected_behavior="The valid request succeeds.",
        )
        invalid = RepairCandidateDraft(
            unified_diff=unified_diff("old\n", "new\n", "compose.yaml"),
            explanation="Change infrastructure.",
            expected_behavior="Not allowed.",
        )
        adapter = FakeRepairAdapter(RepairGenerationDraft(candidates=[valid, invalid]))
        run_id = uuid4()
        result = generate_repairs(
            run_id,
            "a" * 40,
            hypothesis(run_id),
            {"statuses": [409, 409, 503]},
            source,
            adapter,
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].policy_version, POLICY_VERSION)
        self.assertEqual([decision.accepted for decision in result.decisions], [True, False])
        self.assertEqual(adapter.payload["allowed_files"], [APP_PATH])

    def test_one_bounded_retry_uses_sanitized_policy_feedback(self) -> None:
        source = Path(APP_PATH).read_text()
        fixed = source.replace(
            """                    if self.fault_mode == "pool_leak":
                        # Intentional incident fixture: this branch leaves its slot checked out.
                        return_connection = False
""",
            "",
            1,
        )
        invalid = RepairCandidateDraft(
            unified_diff=unified_diff("old\n", "new\n", "compose.yaml"),
            explanation="Invalid scope.",
            expected_behavior="Not allowed.",
        )
        valid = RepairCandidateDraft(
            unified_diff=unified_diff(source, fixed),
            explanation="Release the connection.",
            expected_behavior="The valid request succeeds.",
        )
        adapter = SequenceRepairAdapter(
            [
                RepairGenerationDraft(candidates=[invalid]),
                RepairGenerationDraft(candidates=[valid]),
            ]
        )
        run_id = uuid4()
        result = generate_repairs(
            run_id,
            "a" * 40,
            hypothesis(run_id),
            {"statuses": [409, 409, 503]},
            source,
            adapter,
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(len(adapter.payloads), 2)
        self.assertEqual(
            adapter.payloads[1]["retry_feedback"]["policy_categories"],
            ["forbidden_path"],
        )
        self.assertEqual(result.usage, Usage(40, 20, 2))

    def test_pinned_context_reader_returns_exact_git_blob(self) -> None:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        source = read_pinned_source(Path(".git"), commit, APP_PATH)
        expected = subprocess.run(
            ["git", "show", f"{commit}:{APP_PATH}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(source, expected)


class GeminiRepairAdapterTests(unittest.TestCase):
    def test_adapter_fails_closed_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RepairError, "GEMINI_API_KEY"):
                GeminiRepairAdapter()

    def test_adapter_uses_provider_compatible_schema(self) -> None:
        candidate = GeminiRepairCandidate(
            path=APP_PATH,
            start_line=1,
            end_line=1,
            replacement_text="new",
            explanation="Repair.",
            expected_behavior="Healthy.",
        )
        response = SimpleNamespace(
            parsed=GeminiRepairSchema(candidates=[candidate]),
            usage_metadata=SimpleNamespace(prompt_token_count=9, candidates_token_count=4),
        )
        calls = []
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: calls.append(kwargs) or response
            )
        )
        adapter = GeminiRepairAdapter(client=client, model_id="test-model")
        result = adapter.generate(
            {
                "allowed_files": [APP_PATH],
                "untrusted_repository_context": {"path": APP_PATH, "content": "old\n"},
            }
        )
        self.assertEqual(len(result.draft.candidates), 1)
        self.assertIn("@@ -1 +1 @@", result.draft.candidates[0].unified_diff)
        self.assertEqual(calls[0]["config"].response_schema, GeminiRepairSchema)
        self.assertNotIn("additionalProperties", json.dumps(GeminiRepairSchema.model_json_schema()))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from incidentlab.sandbox.runner import DockerSandboxRunner, _Execution
from incidentlab.verification import (
    SCORE_VERSION,
    RankingFact,
    derive_outcome,
    rank_candidates,
    terminal_state,
)


def checks(**outcomes: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(name=name, outcome=outcome) for name, outcome in outcomes.items()]


class VerificationOutcomeTests(unittest.TestCase):
    def test_baseline_must_reproduce_before_candidate_can_pass(self) -> None:
        values = checks(
            baseline_replay="FAIL",
            patch_apply="PASS",
            build="PASS",
            static="PASS",
            unit="PASS",
            integration="PASS",
            incident_replay="PASS",
        )
        self.assertEqual(derive_outcome(values), "INCONCLUSIVE")

    def test_post_patch_replay_failure_disqualifies_candidate(self) -> None:
        values = checks(
            baseline_replay="PASS",
            patch_apply="PASS",
            build="PASS",
            static="PASS",
            unit="PASS",
            integration="PASS",
            incident_replay="FAIL",
        )
        self.assertEqual(derive_outcome(values), "FAIL")

    def test_missing_or_interrupted_check_is_inconclusive(self) -> None:
        missing = checks(baseline_replay="PASS", patch_apply="PASS")
        interrupted = checks(
            baseline_replay="PASS",
            patch_apply="PASS",
            build="INCONCLUSIVE",
        )
        self.assertEqual(derive_outcome(missing), "INCONCLUSIVE")
        self.assertEqual(derive_outcome(interrupted), "INCONCLUSIVE")

    def test_all_mandatory_facts_are_required_for_pass(self) -> None:
        values = checks(
            baseline_replay="PASS",
            patch_apply="PASS",
            build="PASS",
            static="PASS",
            unit="PASS",
            integration="PASS",
            incident_replay="PASS",
        )
        self.assertEqual(derive_outcome(values), "PASS")

    def test_ranking_is_repeatable_and_prefers_smaller_verified_diff(self) -> None:
        larger = RankingFact(UUID(int=2), "PASS", changed_lines=8, changed_files=1)
        smaller = RankingFact(UUID(int=1), "PASS", changed_lines=2, changed_files=1)
        failed = RankingFact(UUID(int=0), "FAIL", changed_lines=1, changed_files=1)
        first = rank_candidates([larger, failed, smaller])
        second = rank_candidates([smaller, larger, failed])
        self.assertEqual(first, second)
        self.assertEqual(
            [item.candidate_id for item in first],
            [smaller.candidate_id, larger.candidate_id, failed.candidate_id],
        )
        self.assertEqual(SCORE_VERSION, "verification-score-v1")

    def test_terminal_state_uses_persisted_outcomes(self) -> None:
        self.assertEqual(terminal_state(["FAIL"]), "NO_VERIFIED_CANDIDATE")
        self.assertEqual(terminal_state(["FAIL", "INCONCLUSIVE"]), "INCONCLUSIVE")
        self.assertEqual(terminal_state(["FAIL", "PASS"]), "COMPLETED")


class SandboxInconclusiveTests(unittest.TestCase):
    def test_timeout_is_recorded_as_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = DockerSandboxRunner(Path.cwd(), root)
            check = runner._record_check(
                root,
                0,
                "build",
                _Execution(None, b"timed out", "timeout"),
                datetime.now(UTC),
            )
            self.assertEqual(check.outcome, "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()

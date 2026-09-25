import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from incidentlab.verification.agent import drain_once


class VerifierAgentTests(unittest.TestCase):
    def test_waiting_run_is_verified_and_signaled(self) -> None:
        run = SimpleNamespace(id=uuid4(), scenario_id="inventory-underflow")
        candidate = SimpleNamespace(id=uuid4())
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch(
                    "incidentlab.verification.agent.repository.list_runs",
                    return_value=[run],
                ),
                patch(
                    "incidentlab.verification.agent.repository.list_repair_candidates",
                    return_value=[candidate],
                ),
                patch(
                    "incidentlab.verification.agent.repository.list_verifications",
                    return_value=[],
                ),
                patch("incidentlab.verification.agent.verify_run_candidates") as verify,
                patch(
                    "incidentlab.verification.agent.signal_verification_complete",
                    new_callable=AsyncMock,
                ) as signal,
            ):
                processed = drain_once(Path.cwd(), Path(temporary), "incidentlab-sandbox:test")
        self.assertEqual(processed, 1)
        verify.assert_called_once_with(
            run.id,
            Path.cwd(),
            image="incidentlab-sandbox:test",
            runtime_root=Path(temporary),
        )
        signal.assert_awaited_once_with(run.id)

    def test_completed_candidate_is_only_resignaled(self) -> None:
        run = SimpleNamespace(id=uuid4(), scenario_id="pool-exhaustion")
        candidate = SimpleNamespace(id=uuid4())
        verification = SimpleNamespace(candidate_id=candidate.id)
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch(
                    "incidentlab.verification.agent.repository.list_runs",
                    return_value=[run],
                ),
                patch(
                    "incidentlab.verification.agent.repository.list_repair_candidates",
                    return_value=[candidate],
                ),
                patch(
                    "incidentlab.verification.agent.repository.list_verifications",
                    return_value=[verification],
                ),
                patch("incidentlab.verification.agent.verify_run_candidates") as verify,
                patch(
                    "incidentlab.verification.agent.signal_verification_complete",
                    new_callable=AsyncMock,
                ) as signal,
            ):
                processed = drain_once(Path.cwd(), Path(temporary), "incidentlab-sandbox:test")
        self.assertEqual(processed, 1)
        verify.assert_not_called()
        signal.assert_awaited_once_with(run.id)


if __name__ == "__main__":
    unittest.main()

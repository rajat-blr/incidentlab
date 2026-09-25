import unittest
from datetime import UTC, datetime
from uuid import uuid4

from incidentlab.contracts.models import IncidentRun, RunState
from incidentlab.reporting import REPORT_VERSION, assemble_report, render_markdown


class ReportingTests(unittest.TestCase):
    def test_empty_report_is_deterministic_and_honest(self) -> None:
        run = IncidentRun(
            id=uuid4(),
            scenario_id="pool-exhaustion",
            scenario_version=1,
            pinned_commit="a" * 40,
            workflow_id="workflow-1",
            state=RunState.INCONCLUSIVE,
            created_at=datetime(2026, 9, 25, tzinfo=UTC),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
        )
        report = assemble_report(run, [], [], [], [], [])
        markdown = render_markdown(report)
        self.assertEqual(report["report_version"], REPORT_VERSION)
        self.assertIn("State: **INCONCLUSIVE**", markdown)
        self.assertIn("No validated diagnosis was recorded", markdown)
        self.assertIn("No model usage was recorded", markdown)
        self.assertIn("does not deploy or merge", markdown)


if __name__ == "__main__":
    unittest.main()

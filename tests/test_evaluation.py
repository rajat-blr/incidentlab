import json
import tempfile
import unittest
from pathlib import Path

from incidentlab.evaluation import EvaluationConfig, run_evaluation


class EvaluationHarnessTests(unittest.TestCase):
    def test_one_command_compares_baselines_and_exports_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = run_evaluation(output, EvaluationConfig(trials=1, seed=11))
            self.assertEqual(
                [item["system"] for item in report["summary"]],
                ["incidentlab", "deterministic-keyword", "one-shot-uncited"],
            )
            self.assertEqual(len(report["trials"]), 6)
            self.assertTrue(all(item["contained"] for item in report["adversarial"]))
            self.assertTrue((output / "metrics.csv").is_file())
            failures = json.loads((output / "failures.json").read_text())
            self.assertEqual(failures["evaluation_version"], "evaluation-v1")

    def test_trial_count_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            EvaluationConfig(trials=0)


if __name__ == "__main__":
    unittest.main()

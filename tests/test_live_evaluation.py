import unittest

from scripts.evaluate_live import score_report, summary


class LiveEvaluationTests(unittest.TestCase):
    def report(self):
        return {
            "run": {"state": "COMPLETED"},
            "events": [{"kind": "reproduction_recorded"}],
            "evidence": [{"id": "trace-1", "kind": "trace"}],
            "hypotheses": [
                {
                    "supporting_evidence_ids": ["trace-1"],
                    "contradicting_evidence_ids": [],
                }
            ],
            "verifications": [{"outcome": "PASS"}],
            "model_usage": [
                {
                    "provider": "openai",
                    "model_id": "test-model",
                    "prompt_version": prompt,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "estimated_cost_usd": 0.001,
                }
                for prompt in ["diagnosis-v2", "repair-v2"]
            ],
        }

    def test_failures_remain_in_all_rate_denominators(self):
        passing = {
            **score_report(self.report(), "test-model"),
            "scenario_id": "pool-exhaustion",
            "failure_category": None,
        }
        failing = {
            **passing,
            "reproduced": False,
            "citations_valid": False,
            "verified_repair": False,
            "failure_category": "provider_timeout",
            "citation_count": 0,
            "resolved_citation_count": 0,
        }
        row = summary([passing, failing])[-1]
        self.assertEqual(row["trials"], 2)
        self.assertEqual(row["failure_count"], 1)
        for metric in ["reproduction_rate", "citation_validity", "verified_repair_rate"]:
            self.assertEqual(row[metric], 0.5)

    def test_missing_citations_and_gap_support_do_not_pass(self):
        for evidence in [[], [{"id": "trace-1", "kind": "gap"}]]:
            report = self.report()
            report["evidence"] = evidence
            self.assertFalse(score_report(report, "test-model")["citations_valid"])

    def test_curated_or_wrong_model_results_do_not_count_as_live_success(self):
        report = self.report()
        result = score_report(report, "other-model")
        self.assertFalse(result["citations_valid"])
        self.assertFalse(result["verified_repair"])
        report["model_usage"] = []
        self.assertFalse(score_report(report, "test-model")["verified_repair"])


if __name__ == "__main__":
    unittest.main()

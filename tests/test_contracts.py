import json
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from incidentlab.contracts.models import (
    EvidenceItem,
    Hypothesis,
    RunCreateRequest,
    ScenarioManifest,
)


class ContractTests(unittest.TestCase):
    def test_public_scenario_manifest_is_versioned_and_strict(self) -> None:
        with open("scenarios/pool-exhaustion.public.json") as handle:
            manifest = ScenarioManifest.model_validate(json.load(handle))
        self.assertEqual((manifest.id, manifest.version), ("pool-exhaustion", 1))
        with self.assertRaises(ValidationError):
            ScenarioManifest.model_validate({**manifest.model_dump(), "root_cause_label": "leak"})

    def test_evidence_requires_hash_and_ordered_window(self) -> None:
        now = datetime.now(UTC)
        item = EvidenceItem(
            id="ev-1",
            run_id=uuid4(),
            kind="metric",
            source="prometheus",
            retrieval_method="query_range",
            observed_start=now,
            observed_end=now,
            service="inventory",
            summary="pool empty",
            artifact_ref="sha256:abc",
            content_sha256="a" * 64,
        )
        self.assertEqual(item.content_sha256, "a" * 64)
        with self.assertRaises(ValidationError):
            EvidenceItem.model_validate({**item.model_dump(), "content_sha256": "bad"})

    def test_hypothesis_rejects_conflicting_citations(self) -> None:
        with self.assertRaises(ValidationError):
            Hypothesis(
                id="h1",
                run_id=uuid4(),
                summary="pool leak",
                mechanism="connection leak",
                supporting_evidence_ids=["ev-1"],
                contradicting_evidence_ids=["ev-1"],
                confidence="medium",
            )

    def test_run_creation_requires_idempotency_key(self) -> None:
        with self.assertRaises(ValidationError):
            RunCreateRequest(scenario_id="pool-exhaustion", idempotency_key="")

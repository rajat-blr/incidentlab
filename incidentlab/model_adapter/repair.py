"""Bounded repair generation with deterministic post-model policy enforcement."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from incidentlab.contracts.models import (
    Hypothesis,
    RepairCandidate,
    RepairGenerationDraft,
)
from incidentlab.model_adapter.diagnosis import Usage
from incidentlab.policy.repair import POLICY_VERSION, PolicyDecision, RepairPolicy

PROMPT_VERSION = "repair-v7"

SCENARIO_FAULT_MODES = {
    "pool-exhaustion": "pool_leak",
    "inventory-underflow": "inventory_underflow",
}
SCENARIO_CHANGED_SOURCE_MARKERS = {
    "pool-exhaustion": ('"pool_leak"', "return_connection"),
    "inventory-underflow": ('"inventory_underflow"', "row[0] < quantity"),
}


class RepairError(RuntimeError):
    """A repair response could not be safely validated."""


@dataclass(frozen=True)
class RepairModelResult:
    draft: RepairGenerationDraft | dict
    usage: Usage


class RepairAdapter(Protocol):
    provider: str
    model_id: str

    def generate(self, payload: dict) -> RepairModelResult: ...


@dataclass(frozen=True)
class RepairGenerationResult:
    candidates: tuple[RepairCandidate, ...]
    decisions: tuple[PolicyDecision, ...]
    usage: Usage


def generate_repairs(
    run_id: UUID,
    target_commit: str,
    hypothesis: Hypothesis,
    reproduction: dict,
    pinned_source: str,
    adapter: RepairAdapter,
    policy: RepairPolicy | None = None,
    scenario_id: str | None = None,
) -> RepairGenerationResult:
    if len(pinned_source.encode()) > 32 * 1024:
        raise RepairError("repository context exceeds the byte limit")
    repair_policy = policy or RepairPolicy()
    payload = {
        "task": (
            "Propose a minimal repair for the approved root-cause hypothesis and active "
            "incident scenario. Make the active scenario replay healthy without changing other "
            "scenario fixtures."
        ),
        "active_scenario_id": scenario_id,
        "active_fault_mode": SCENARIO_FAULT_MODES.get(scenario_id or ""),
        "allowed_changed_source_markers": list(
            SCENARIO_CHANGED_SOURCE_MARKERS.get(scenario_id or "", ())
        ),
        "target_commit": target_commit,
        "approved_hypothesis": hypothesis.model_dump(mode="json"),
        "failing_reproduction": reproduction,
        "allowed_files": list(repair_policy.allowed_paths),
        "untrusted_repository_context": {
            "path": "sample_service/app.py",
            "content": pinned_source,
            "numbered_content": "\n".join(
                f"{number}: {line}"
                for number, line in enumerate(pinned_source.splitlines(), start=1)
            ),
        },
    }
    decisions: list[PolicyDecision] = []
    candidates: list[RepairCandidate] = []
    seen_digests: set[str] = set()
    usage = Usage()
    attempt_payload = payload
    for attempt in range(2):
        model_result = adapter.generate(attempt_payload)
        usage += model_result.usage
        try:
            draft = RepairGenerationDraft.model_validate(model_result.draft)
        except ValidationError as error:
            raise RepairError(f"repair schema validation failed: {error}") from error
        for index, proposed in enumerate(draft.candidates):
            decision = repair_policy.evaluate(proposed, pinned_source)
            markers = SCENARIO_CHANGED_SOURCE_MARKERS.get(scenario_id or "", ())
            changed_lines = [
                line
                for line in proposed.unified_diff.splitlines()
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            ]
            if (
                decision.accepted
                and markers
                and not any(marker in line for marker in markers for line in changed_lines)
            ):
                decision = PolicyDecision(
                    False,
                    "scenario_scope",
                    f"candidate does not change the active {scenario_id} fault mechanism",
                    (),
                    hashlib.sha256(proposed.unified_diff.encode()).hexdigest(),
                )
            if decision.accepted and decision.diff_sha256 in seen_digests:
                decision = PolicyDecision(
                    False,
                    "duplicate",
                    "duplicate candidate diff",
                    (),
                    decision.diff_sha256,
                )
            decisions.append(decision)
            if not decision.accepted or len(candidates) >= 2:
                continue
            seen_digests.add(decision.diff_sha256)
            candidate_id = uuid5(
                NAMESPACE_URL,
                f"incidentlab:{run_id}:{PROMPT_VERSION}:{attempt}:{index}:{decision.diff_sha256}",
            )
            candidates.append(
                RepairCandidate(
                    id=candidate_id,
                    run_id=run_id,
                    target_commit=target_commit,
                    unified_diff=proposed.unified_diff,
                    explanation=proposed.explanation,
                    expected_behavior=proposed.expected_behavior,
                    changed_paths=list(decision.changed_paths),
                    generator_id=adapter.model_id,
                    diff_sha256=decision.diff_sha256,
                    policy_status="accepted",
                    policy_version=POLICY_VERSION,
                )
            )
        if candidates:
            break
        attempt_payload = {
            **payload,
            "retry_feedback": {
                "instruction": (
                    "All previous candidates were rejected. Return a corrected, minimal, "
                    "syntactically complete replacement."
                ),
                "policy_categories": [decision.category for decision in decisions],
                "policy_details": [decision.detail for decision in decisions],
                "allowed_changed_source_markers": list(
                    SCENARIO_CHANGED_SOURCE_MARKERS.get(scenario_id or "", ())
                ),
            },
        }
    return RepairGenerationResult(tuple(candidates), tuple(decisions), usage)

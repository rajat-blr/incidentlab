"""Fact-derived verification outcomes and deterministic candidate ranking."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

SCORE_VERSION = "verification-score-v1"
REQUIRED_POST_PATCH_CHECKS = (
    "patch_apply",
    "build",
    "static",
    "unit",
    "integration",
    "incident_replay",
)


class CheckFact(Protocol):
    name: str
    outcome: str


@dataclass(frozen=True)
class RankingFact:
    candidate_id: UUID
    outcome: str
    changed_lines: int
    changed_files: int


@dataclass(frozen=True)
class RankedCandidate:
    candidate_id: UUID
    rank: int
    score: dict[str, int]


def derive_outcome(checks: Iterable[CheckFact]) -> str:
    """Derive the result only from mandatory recorded checks."""
    by_name = {check.name: check for check in checks}
    baseline = by_name.get("baseline_replay")
    if baseline is None or baseline.outcome != "PASS":
        return "INCONCLUSIVE"

    required = [by_name.get(name) for name in REQUIRED_POST_PATCH_CHECKS]
    if any(check is not None and check.outcome == "INCONCLUSIVE" for check in required):
        return "INCONCLUSIVE"
    if any(check is not None and check.outcome == "FAIL" for check in required):
        return "FAIL"
    if any(check is None for check in required):
        return "INCONCLUSIVE"
    if all(check is not None and check.outcome == "PASS" for check in required):
        return "PASS"
    return "INCONCLUSIVE"


def changed_line_count(unified_diff: str) -> int:
    return sum(
        1
        for line in unified_diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def rank_candidates(facts: Iterable[RankingFact]) -> tuple[RankedCandidate, ...]:
    """Rank repeatably: mandatory outcome, then smaller diff, then UUID."""
    outcome_order = {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}
    ordered = sorted(
        facts,
        key=lambda fact: (
            outcome_order[fact.outcome],
            fact.changed_files,
            fact.changed_lines,
            str(fact.candidate_id),
        ),
    )
    return tuple(
        RankedCandidate(
            candidate_id=fact.candidate_id,
            rank=index,
            score={
                "mandatory_outcome": outcome_order[fact.outcome],
                "changed_files": fact.changed_files,
                "changed_lines": fact.changed_lines,
            },
        )
        for index, fact in enumerate(ordered, start=1)
    )


def terminal_state(outcomes: Iterable[str]) -> str:
    values = tuple(outcomes)
    if "PASS" in values:
        return "COMPLETED"
    if "INCONCLUSIVE" in values or not values:
        return "INCONCLUSIVE"
    return "NO_VERIFIED_CANDIDATE"

"""Strict diagnosis boundary around one model provider and immutable evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from incidentlab.contracts.models import (
    DiagnosisDraft,
    EvidenceItem,
    EvidenceLookup,
    Hypothesis,
)

PROMPT_VERSION = "diagnosis-v2"
MAX_FOLLOW_UP_QUERIES = 2
MAX_TOOL_RESULT_BYTES = 32_000

TOOL_KINDS = {
    "query_metric": "metric",
    "fetch_trace": "trace",
    "search_logs": "log",
    "search_repository": "commit",
}

SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization[\"'=:\s]+)([^\s\"',}]+)"),
    re.compile(r"(?i)((?:api[_-]?key|token|password)[\"'=:\s]+)([^\s\"',}]+)"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
)


class DiagnosisError(RuntimeError):
    pass


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            latency_ms=self.latency_ms + other.latency_ms,
        )


@dataclass(frozen=True)
class ModelResult:
    draft: DiagnosisDraft | dict
    usage: Usage


@dataclass(frozen=True)
class DiagnosisResult:
    hypotheses: tuple[Hypothesis, ...]
    usage: Usage
    tool_call_count: int
    tool_requests: tuple[EvidenceLookup, ...]


class DiagnosisAdapter(Protocol):
    provider: str
    model_id: str

    def generate(
        self,
        evidence: list[dict],
        *,
        tool_results: list[dict] | None = None,
        allow_follow_ups: bool = True,
        validation_feedback: dict | None = None,
    ) -> ModelResult: ...


class ArtifactLookup(Protocol):
    def __call__(self, artifact_id: UUID) -> tuple[object, bytes] | None: ...


def redact_untrusted_text(value: str) -> str:
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            value = pattern.sub(r"\1[REDACTED]", value)
        else:
            value = pattern.sub("[REDACTED]", value)
    return value


def _validate_lookup(request: EvidenceLookup, evidence_by_id: dict[str, EvidenceItem]) -> None:
    item = evidence_by_id.get(request.evidence_id)
    if item is None:
        raise DiagnosisError(f"tool request cites nonexistent evidence: {request.evidence_id}")
    expected_kind = TOOL_KINDS[request.tool]
    if item.kind != expected_kind:
        raise DiagnosisError(
            f"tool {request.tool} cannot inspect evidence kind {item.kind}: {item.id}"
        )


def _tool_result(
    request: EvidenceLookup,
    evidence_by_id: dict[str, EvidenceItem],
    artifact_lookup: ArtifactLookup,
) -> dict:
    _validate_lookup(request, evidence_by_id)
    item = evidence_by_id[request.evidence_id]
    artifact_id = UUID(item.artifact_ref.rsplit("/", 1)[-1])
    result = artifact_lookup(artifact_id)
    if result is None:
        raise DiagnosisError(f"artifact not found for evidence: {item.id}")
    metadata, content = result
    expected_hash = getattr(metadata, "content_sha256", None)
    if expected_hash != item.content_sha256 or hashlib.sha256(content).hexdigest() != expected_hash:
        raise DiagnosisError(f"artifact hash metadata mismatch for evidence: {item.id}")
    raw_content = content
    try:
        envelope = json.loads(content)
        if isinstance(envelope, dict) and isinstance(envelope.get("response_base64"), str):
            raw_content = base64.b64decode(envelope["response_base64"], validate=True)
            if hashlib.sha256(raw_content).hexdigest() != envelope.get("response_sha256"):
                raise DiagnosisError(f"inner response hash mismatch for evidence: {item.id}")
    except (ValueError, TypeError, json.JSONDecodeError):
        raw_content = content
    snippet = raw_content[:MAX_TOOL_RESULT_BYTES].decode("utf-8", errors="replace")
    return {
        "tool": request.tool,
        "evidence_id": item.id,
        "content": redact_untrusted_text(snippet),
        "truncated": len(raw_content) > MAX_TOOL_RESULT_BYTES,
    }


def _validated_draft(value: DiagnosisDraft | dict) -> DiagnosisDraft:
    try:
        return value if isinstance(value, DiagnosisDraft) else DiagnosisDraft.model_validate(value)
    except ValidationError as error:
        raise DiagnosisError(f"model output failed schema validation: {error}") from error


def _validate_hypotheses(draft: DiagnosisDraft, evidence_by_id: dict[str, EvidenceItem]) -> None:
    for hypothesis in draft.hypotheses:
        citations = hypothesis.supporting_evidence_ids + hypothesis.contradicting_evidence_ids
        missing = sorted(set(citations) - set(evidence_by_id))
        if missing:
            raise DiagnosisError(f"hypothesis cites nonexistent evidence: {missing}")
        unsupported = [
            evidence_id
            for evidence_id in hypothesis.supporting_evidence_ids
            if evidence_by_id[evidence_id].kind == "gap"
        ]
        if unsupported:
            raise DiagnosisError(f"gap evidence cannot support a hypothesis: {unsupported}")
        for check in hypothesis.proposed_checks:
            _validate_lookup(check, evidence_by_id)


def diagnose(
    run_id: UUID,
    evidence: list[EvidenceItem],
    adapter: DiagnosisAdapter,
    artifact_lookup: ArtifactLookup,
) -> DiagnosisResult:
    evidence_by_id = {item.id: item for item in evidence}
    if not evidence_by_id:
        raise DiagnosisError("diagnosis requires evidence")
    model_evidence = [
        {
            "id": item.id,
            "kind": item.kind,
            "source": item.source,
            "service": item.service,
            "summary": redact_untrusted_text(item.summary),
            "observed_start": item.observed_start.isoformat(),
            "observed_end": item.observed_end.isoformat(),
        }
        for item in evidence
    ]
    first = adapter.generate(model_evidence)
    draft = _validated_draft(first.draft)
    usage = first.usage
    requests = draft.follow_up_queries
    if len(requests) > MAX_FOLLOW_UP_QUERIES:
        raise DiagnosisError("follow-up query budget exceeded")
    tool_results: list[dict] = []
    seen_requests: set[tuple[str, str]] = set()
    for request in requests:
        key = (request.tool, request.evidence_id)
        if key in seen_requests:
            raise DiagnosisError("duplicate follow-up query")
        seen_requests.add(key)
        tool_results.append(_tool_result(request, evidence_by_id, artifact_lookup))
    if tool_results:
        final = adapter.generate(
            model_evidence,
            tool_results=tool_results,
            allow_follow_ups=False,
        )
        draft = _validated_draft(final.draft)
        usage += final.usage
        if draft.follow_up_queries:
            raise DiagnosisError("follow-up query budget exhausted")
    try:
        _validate_hypotheses(draft, evidence_by_id)
    except DiagnosisError as error:
        correction = adapter.generate(
            model_evidence,
            tool_results=tool_results,
            allow_follow_ups=False,
            validation_feedback={
                "error": str(error),
                "allowed_evidence_ids": sorted(evidence_by_id),
            },
        )
        draft = _validated_draft(correction.draft)
        usage += correction.usage
        if draft.follow_up_queries:
            raise DiagnosisError("correction cannot request follow-up queries")
        _validate_hypotheses(draft, evidence_by_id)
    hypotheses = []
    for index, candidate in enumerate(draft.hypotheses):
        serialized = json.dumps(candidate.model_dump(mode="json"), sort_keys=True)
        hypothesis_id = uuid5(
            NAMESPACE_URL,
            f"incidentlab:{run_id}:hypothesis:{index}:{serialized}",
        )
        hypotheses.append(
            Hypothesis(
                id=hypothesis_id,
                run_id=run_id,
                **candidate.model_dump(),
                model_id=adapter.model_id,
                prompt_version=PROMPT_VERSION,
            )
        )
    return DiagnosisResult(tuple(hypotheses), usage, len(tool_results), tuple(requests))


def monotonic_milliseconds(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))

"""Bounded telemetry and Git collectors with immutable, attributable outputs."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from incidentlab.contracts.models import EvidenceItem

MAX_ARTIFACT_BYTES = 2_000_000


@dataclass(frozen=True)
class Artifact:
    id: UUID
    source: str
    media_type: str
    content: bytes
    content_sha256: str
    retrieved_at: datetime


@dataclass(frozen=True)
class EvidenceBundle:
    artifacts: tuple[Artifact, ...]
    items: tuple[EvidenceItem, ...]


@dataclass(frozen=True)
class Query:
    key: str
    kind: str
    source: str
    service: str
    url: str


Fetch = Callable[[str], bytes]


def http_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=0.75) as response:
        content = response.read(MAX_ARTIFACT_BYTES + 1)
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError("response exceeds evidence artifact limit")
    return content


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _artifact(run_id: UUID, source: str, content: bytes, retrieved_at: datetime) -> Artifact:
    digest = hashlib.sha256(content).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"incidentlab:{run_id}:{source}:{digest}")
    return Artifact(artifact_id, source, "application/json", content, digest, retrieved_at)


def _query_artifact(
    run_id: UUID,
    query: Query,
    response: bytes | None,
    retrieved_at: datetime,
    error: Exception | None = None,
) -> Artifact:
    envelope = {
        "query_url": query.url,
        "response_base64": base64.b64encode(response).decode() if response is not None else None,
        "response_sha256": hashlib.sha256(response).hexdigest() if response is not None else None,
        "retrieved_at": retrieved_at.isoformat(),
        "error": (
            {"type": type(error).__name__, "message": str(error)} if error is not None else None
        ),
    }
    return _artifact(run_id, query.source, _canonical(envelope), retrieved_at)


def _evidence(
    run_id: UUID,
    query: Query,
    artifact: Artifact,
    start: datetime,
    end: datetime,
    summary: str,
    *,
    kind: str | None = None,
) -> EvidenceItem:
    evidence_kind = kind or query.kind
    item_id = f"ev-{uuid5(NAMESPACE_URL, f'incidentlab:{run_id}:{query.key}:{evidence_kind}')}"
    return EvidenceItem(
        id=item_id,
        run_id=run_id,
        kind=evidence_kind,
        source=query.source,
        retrieval_method=("local_git_metadata" if query.source == "git" else "bounded_http_query"),
        observed_start=start,
        observed_end=end,
        service=query.service,
        summary=summary,
        artifact_ref=f"/evidence/artifacts/{artifact.id}",
        content_sha256=artifact.content_sha256,
    )


def _parse(query: Query, payload: bytes) -> str | None:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("top-level response is not an object")
    data = value.get("data")
    if query.kind == "trace":
        if not isinstance(data, list) or not data:
            return None
        traces = [entry for entry in data if isinstance(entry, dict)]
        if not traces:
            raise ValueError("trace results are malformed")
        trace_ids = sorted(
            {entry.get("traceID") for entry in traces if isinstance(entry.get("traceID"), str)}
        )
        if not trace_ids:
            raise ValueError("trace results do not contain trace IDs")
        spans = [
            span for entry in traces for span in entry.get("spans", []) if isinstance(span, dict)
        ]
        timed_out = any(
            span.get("operationName") == "db.pool.acquire"
            and any(
                tag.get("key") == "db.pool.timeout" and tag.get("value") is True
                for tag in span.get("tags", [])
                if isinstance(tag, dict)
            )
            for span in spans
        )
        return (
            f"Found {len(trace_ids)} correlated trace(s); database acquisition timeout={timed_out}."
        )
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise ValueError("query result is malformed")
    results = data["result"]
    if not results:
        return None
    if query.kind == "metric":
        samples: list[float] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            pairs = list(result.get("values", []))
            if "value" in result:
                pairs.append(result["value"])
            for pair in pairs:
                try:
                    samples.append(float(pair[1]))
                except (IndexError, TypeError, ValueError):
                    continue
        if not samples:
            raise ValueError("metric series have no samples")
        return (
            f"Found {len(results)} metric series with {len(samples)} sample(s); "
            f"minimum={min(samples):g}, maximum={max(samples):g}, latest={samples[-1]:g}."
        )
    valid_lines = 0
    malformed_lines = 0
    for stream in results:
        for pair in stream.get("values", []) if isinstance(stream, dict) else []:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[1], str):
                malformed_lines += 1
                continue
            try:
                event = json.loads(pair[1])
            except json.JSONDecodeError:
                malformed_lines += 1
            else:
                valid_lines += isinstance(event, dict)
    if valid_lines == 0:
        if malformed_lines:
            raise ValueError("all log records are malformed")
        return None
    return f"Found {valid_lines} structured log record(s); malformed={malformed_lines}."


def telemetry_queries(
    run_id: UUID, start: datetime, end: datetime, request_ids: list[str]
) -> tuple[Query, ...]:
    prometheus = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
    jaeger = os.environ.get("JAEGER_URL", "http://jaeger:16686")
    loki = os.environ.get("LOKI_URL", "http://loki:3100")
    start_seconds, end_seconds = start.timestamp(), end.timestamp()
    trace_args = urllib.parse.urlencode(
        {
            "service": "checkout",
            "start": int(start_seconds * 1_000_000),
            "end": int(end_seconds * 1_000_000),
            "limit": 20,
            "tags": json.dumps(
                {"incidentlab.request_id": request_ids[-1] if request_ids else "__missing__"}
            ),
        }
    )
    queries = [
        Query(
            "trace",
            "trace",
            "jaeger",
            "checkout,inventory",
            f"{jaeger}/api/traces?{trace_args}",
        )
    ]
    metrics = (
        ("pool-available", "incidentlab_db_pool_available", "inventory", ""),
        ("pool-timeouts", "incidentlab_db_pool_timeouts_total", "inventory", ""),
        ("gateway-503", "incidentlab_gateway_requests_total", "checkout", ',status="503"'),
    )
    for key, name, service, extra_selector in metrics:
        expression = f'{name}{{incidentlab_run_id="{run_id}"{extra_selector}}}'
        args = urllib.parse.urlencode(
            {"query": expression, "start": start_seconds, "end": end_seconds, "step": "1s"}
        )
        queries.append(
            Query(
                key,
                "metric",
                "prometheus",
                service,
                f"{prometheus}/api/v1/query_range?{args}",
            )
        )
    request_match = request_ids[-1] if request_ids else "__missing__"
    for service in ("inventory", "checkout"):
        expression = f'{{service_name="{service}"}} |= {json.dumps(request_match)}'
        args = urllib.parse.urlencode(
            {
                "query": expression,
                "start": int(start_seconds * 1_000_000_000),
                "end": int(end_seconds * 1_000_000_000),
                "limit": 100,
            }
        )
        queries.append(
            Query(
                f"logs-{service}",
                "log",
                "loki",
                service,
                f"{loki}/loki/api/v1/query_range?{args}",
            )
        )
    return tuple(queries)


def collect_telemetry(
    run_id: UUID,
    start: datetime,
    end: datetime,
    request_ids: list[str],
    *,
    fetch: Fetch = http_fetch,
    attempts: int = 5,
    delay_seconds: float = 1.0,
) -> EvidenceBundle:
    """Poll only the fixed scenario queries and retain exact responses once data arrives."""
    pending = {query.key: query for query in telemetry_queries(run_id, start, end, request_ids)}
    artifacts: dict[str, Artifact] = {}
    items: dict[str, EvidenceItem] = {}
    last: dict[str, tuple[Query, Artifact, str]] = {}
    for attempt in range(attempts):
        for key, query in list(pending.items()):
            retrieved_at = datetime.now(UTC)
            content: bytes | None = None
            try:
                content = fetch(query.url)
                artifact = _query_artifact(run_id, query, content, retrieved_at)
                artifacts[key] = artifact
                summary = _parse(query, content)
                last[key] = (query, artifact, "no matching telemetry")
                if summary is None:
                    continue
                item = _evidence(run_id, query, artifact, start, end, summary)
                items[item.id] = item
                del pending[key]
            except Exception as error:  # collectors convert source failures into attributable gaps
                artifact = _query_artifact(run_id, query, content, retrieved_at, error)
                artifacts[key] = artifact
                last[key] = (query, artifact, f"malformed or unavailable telemetry: {error}")
        if not pending:
            break
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    for key, query in pending.items():
        query, artifact, reason = last.get(key) or (
            query,
            _query_artifact(
                run_id,
                query,
                None,
                datetime.now(UTC),
                RuntimeError("not collected"),
            ),
            "telemetry was not collected",
        )
        artifacts[key] = artifact
        item = _evidence(run_id, query, artifact, start, end, reason, kind="gap")
        items[item.id] = item
    return EvidenceBundle(tuple(artifacts.values()), tuple(items.values()))


def collect_git_metadata(run_id: UUID, pinned_commit: str, git_dir: Path) -> EvidenceBundle:
    head = (git_dir / "HEAD").read_text().strip() if (git_dir / "HEAD").is_file() else None
    reference = head.removeprefix("ref: ") if head and head.startswith("ref: ") else None
    resolved = None
    if reference and (git_dir / reference).is_file():
        resolved = (git_dir / reference).read_text().strip()
    elif head and not reference:
        resolved = head
    if resolved is None and (git_dir / "packed-refs").is_file() and reference:
        for line in (git_dir / "packed-refs").read_text().splitlines():
            if line and not line.startswith(("#", "^")):
                commit, name = line.split(" ", 1)
                if name == reference:
                    resolved = commit
                    break
    payload = _canonical(
        {"head": head, "head_commit": resolved, "pinned_commit": pinned_commit, "ref": reference}
    )
    retrieved = datetime.now(UTC)
    artifact = _artifact(run_id, "git", payload, retrieved)
    query = Query("git-commit", "commit", "git", "repository", "local:.git/HEAD")
    if resolved == pinned_commit:
        summary = f"Run is pinned to Git commit {pinned_commit}."
        kind = "commit"
    else:
        summary = "Pinned commit could not be matched to the checked-out Git HEAD."
        kind = "gap"
    item = _evidence(run_id, query, artifact, retrieved, retrieved, summary, kind=kind)
    return EvidenceBundle((artifact,), (item,))


def combine(*bundles: EvidenceBundle) -> EvidenceBundle:
    artifacts = {artifact.id: artifact for bundle in bundles for artifact in bundle.artifacts}
    items = {item.id: item for bundle in bundles for item in bundle.items}
    return EvidenceBundle(tuple(artifacts.values()), tuple(items.values()))

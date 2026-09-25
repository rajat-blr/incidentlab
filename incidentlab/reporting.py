"""Deterministic review report assembly and Markdown rendering."""

from __future__ import annotations

from incidentlab.contracts.models import (
    EvidenceItem,
    Hypothesis,
    IncidentRun,
    RepairCandidate,
    VerificationRun,
)

REPORT_VERSION = "incident-report-v1"


def assemble_report(
    run: IncidentRun,
    evidence: list[EvidenceItem],
    hypotheses: list[Hypothesis],
    candidates: list[RepairCandidate],
    verifications: list[VerificationRun],
    events: list[dict],
) -> dict:
    return {
        "report_version": REPORT_VERSION,
        "run": run.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "hypotheses": [item.model_dump(mode="json") for item in hypotheses],
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "verifications": [item.model_dump(mode="json") for item in verifications],
        "events": events,
        "limitations": [
            "This is a local educational system and does not deploy or merge changes.",
            "Verification applies only to the pinned commit and recorded sandbox environment.",
            "Model output is untrusted until deterministic policy and verification complete.",
        ],
    }


def render_markdown(report: dict) -> str:
    run = report["run"]
    lines = [
        f"# IncidentLab report: {run['scenario_id']}",
        "",
        f"- Report version: `{report['report_version']}`",
        f"- Run: `{run['id']}`",
        f"- State: **{run['state']}**",
        f"- Pinned commit: `{run['pinned_commit']}`",
        "",
        "## Diagnosis",
        "",
    ]
    if report["hypotheses"]:
        for hypothesis in report["hypotheses"]:
            lines.extend(
                [
                    f"### {hypothesis['summary']}",
                    "",
                    hypothesis["mechanism"],
                    "",
                    f"Confidence: **{hypothesis['confidence']}**",
                    "",
                    "Supporting evidence: "
                    + ", ".join(f"`{value}`" for value in hypothesis["supporting_evidence_ids"]),
                    "",
                ]
            )
    else:
        lines.extend(["No validated diagnosis was recorded.", ""])
    lines.extend(["## Repair candidates", ""])
    if report["candidates"]:
        verification_by_candidate = {item["candidate_id"]: item for item in report["verifications"]}
        for candidate in report["candidates"]:
            verification = verification_by_candidate.get(candidate["id"])
            outcome = verification["outcome"] if verification else "NOT_VERIFIED"
            rank = verification["rank"] if verification else None
            lines.extend(
                [
                    f"### Candidate `{candidate['id']}`",
                    "",
                    f"- Outcome: **{outcome}**",
                    f"- Rank: {rank if rank is not None else 'unranked'}",
                    f"- Policy: `{candidate['policy_version']}`",
                    f"- Diff SHA-256: `{candidate['diff_sha256']}`",
                    f"- Changed paths: {', '.join(candidate['changed_paths'])}",
                    "",
                    candidate["explanation"],
                    "",
                    "```diff",
                    candidate["unified_diff"].rstrip(),
                    "```",
                    "",
                ]
            )
    else:
        lines.extend(["No policy-accepted repair candidate was recorded.", ""])
    lines.extend(["## Verification", ""])
    for verification in report["verifications"]:
        lines.extend(
            [
                f"### Candidate `{verification['candidate_id']}` — {verification['outcome']}",
                "",
                f"Score version: `{verification['score_version']}`",
                "",
                "| Check | Outcome | Exit code | Artifact |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for check in verification["checks"]:
            lines.append(
                f"| {check['name']} | {check['outcome']} | "
                f"{check['exit_code'] if check['exit_code'] is not None else '—'} | "
                f"`{check['content_sha256']}` |"
            )
        lines.append("")
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"

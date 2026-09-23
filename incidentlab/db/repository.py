"""Durable PostgreSQL operations used by the API and Temporal Activities."""

import os
from datetime import UTC, datetime
from functools import lru_cache
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from incidentlab.contracts.models import IncidentRun, RunState
from incidentlab.db.tables import approvals, audit_events, incident_runs, run_outputs


@lru_cache
def engine() -> sa.Engine:
    return sa.create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def _run_from_row(row: sa.RowMapping) -> IncidentRun:
    return IncidentRun(
        id=row["id"],
        scenario_id=row["scenario_id"],
        scenario_version=row["scenario_version"],
        pinned_commit=row["pinned_commit"],
        workflow_id=row["workflow_id"],
        state=row["state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_or_get_run(
    scenario_id: str, scenario_version: int, idempotency_key: str, pinned_commit: str
) -> tuple[IncidentRun, bool]:
    run_id = uuid5(NAMESPACE_URL, f"incidentlab:{idempotency_key}")
    workflow_id = f"incidentlab-run-{run_id}"
    now = datetime.now(UTC)
    with engine().begin() as connection:
        created = connection.execute(
            insert(incident_runs)
            .values(
                id=run_id,
                scenario_id=scenario_id,
                scenario_version=scenario_version,
                pinned_commit=pinned_commit,
                idempotency_key=idempotency_key,
                workflow_id=workflow_id,
                state=RunState.CREATED.value,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[incident_runs.c.idempotency_key])
            .returning(incident_runs.c.id)
        ).scalar_one_or_none()
        row = (
            connection.execute(
                sa.select(incident_runs).where(incident_runs.c.idempotency_key == idempotency_key)
            )
            .mappings()
            .one()
        )
        if created is not None:
            _insert_event(
                connection,
                run_id,
                "run_created",
                "api",
                idempotency_key,
                f"run:{run_id}:created",
                {"scenario_id": scenario_id, "scenario_version": scenario_version},
                now,
            )
    return _run_from_row(row), created is not None


def get_run(run_id: UUID) -> IncidentRun | None:
    with engine().connect() as connection:
        row = (
            connection.execute(sa.select(incident_runs).where(incident_runs.c.id == run_id))
            .mappings()
            .one_or_none()
        )
    return _run_from_row(row) if row else None


def list_events(run_id: UUID) -> list[dict]:
    with engine().connect() as connection:
        rows = (
            connection.execute(
                sa.select(audit_events)
                .where(audit_events.c.run_id == run_id)
                .order_by(audit_events.c.created_at, audit_events.c.id)
            )
            .mappings()
            .all()
        )
    return [
        {
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "kind": row["kind"],
            "actor": row["actor"],
            "correlation_id": row["correlation_id"],
            "created_at": row["created_at"].isoformat(),
            "details": row["details"],
        }
        for row in rows
    ]


def _insert_event(
    connection: sa.Connection,
    run_id: UUID,
    kind: str,
    actor: str,
    correlation_id: str,
    effect_key: str,
    details: dict,
    created_at: datetime,
) -> bool:
    inserted = connection.execute(
        insert(audit_events)
        .values(
            id=uuid4(),
            run_id=run_id,
            kind=kind,
            actor=actor,
            correlation_id=correlation_id,
            effect_key=effect_key,
            created_at=created_at,
            details=details,
        )
        .on_conflict_do_nothing(index_elements=[audit_events.c.effect_key])
        .returning(audit_events.c.id)
    ).scalar_one_or_none()
    return inserted is not None


def transition_run(
    run_id: UUID, state: RunState, effect_key: str, details: dict | None = None
) -> bool:
    now = datetime.now(UTC)
    with engine().begin() as connection:
        inserted = _insert_event(
            connection,
            run_id,
            "state_changed",
            "workflow",
            str(run_id),
            effect_key,
            {"state": state.value, **(details or {})},
            now,
        )
        if inserted:
            values = {"state": state.value, "updated_at": now}
            if state == RunState.FAILED:
                values["failure_category"] = (details or {}).get("failure_category", "unknown")
            connection.execute(
                incident_runs.update().where(incident_runs.c.id == run_id).values(**values)
            )
    return inserted


def record_output(run_id: UUID, column: str, payload: dict, effect_key: str) -> bool:
    if column not in {
        "reproduction",
        "evidence_placeholder",
        "diagnosis_placeholder",
        "repair_placeholder",
        "verification_placeholder",
        "report_placeholder",
    }:
        raise ValueError("invalid output column")
    now = datetime.now(UTC)
    with engine().begin() as connection:
        inserted = _insert_event(
            connection,
            run_id,
            f"{column}_recorded",
            "worker",
            str(run_id),
            effect_key,
            payload,
            now,
        )
        if inserted:
            statement = insert(run_outputs).values(
                run_id=run_id, updated_at=now, **{column: payload}
            )
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[run_outputs.c.run_id],
                    set_={column: payload, "updated_at": now},
                )
            )
    return inserted


def record_approval(
    run_id: UUID, actor: str, decision: str, policy_version: str = "approval-v1"
) -> tuple[dict, bool]:
    now = datetime.now(UTC)
    approval_id = uuid5(NAMESPACE_URL, f"incidentlab:{run_id}:generate_repair")
    with engine().begin() as connection:
        created = connection.execute(
            insert(approvals)
            .values(
                id=approval_id,
                run_id=run_id,
                actor=actor,
                action="generate_repair",
                decision=decision,
                policy_version=policy_version,
                decided_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_approvals_run_action")
            .returning(approvals.c.id)
        ).scalar_one_or_none()
        row = (
            connection.execute(
                sa.select(approvals).where(
                    approvals.c.run_id == run_id, approvals.c.action == "generate_repair"
                )
            )
            .mappings()
            .one()
        )
        if created is not None:
            _insert_event(
                connection,
                run_id,
                "repair_approval",
                actor,
                str(run_id),
                f"run:{run_id}:repair-approval",
                {"decision": decision, "policy_version": policy_version},
                now,
            )
    return dict(row), created is not None


def get_approval(run_id: UUID) -> dict | None:
    with engine().connect() as connection:
        row = (
            connection.execute(
                sa.select(approvals).where(
                    approvals.c.run_id == run_id, approvals.c.action == "generate_repair"
                )
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row else None

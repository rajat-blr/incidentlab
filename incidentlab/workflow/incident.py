"""Durable incident workflow with approval and externally isolated verification."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2,
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=3,
)


@workflow.defn
class IncidentWorkflow:
    def __init__(self) -> None:
        self.approval: str | None = None
        self.verification_available = False
        self.cancel_requested = False
        self.cancel_actor = "unknown"

    async def _activity(
        self,
        name: str,
        data: dict,
        *,
        long_running: bool = False,
        timeout_seconds: int | None = None,
    ) -> dict:
        return await workflow.execute_activity(
            name,
            data,
            result_type=dict,
            start_to_close_timeout=timedelta(
                seconds=timeout_seconds or (45 if long_running else 15)
            ),
            heartbeat_timeout=timedelta(seconds=5) if long_running else None,
            retry_policy=ACTIVITY_RETRY,
        )

    async def _transition(
        self, run_id: str, state: str, step: str, details: dict | None = None
    ) -> None:
        await self._activity(
            "transition_run",
            {
                "run_id": run_id,
                "state": state,
                "effect_key": f"run:{run_id}:state:{step}",
                "details": details or {},
            },
        )

    async def _stop_if_cancelled(self, run_id: str, step: str) -> bool:
        if not self.cancel_requested:
            return False
        await self._transition(
            run_id, "CANCELLED", f"cancelled:{step}", {"actor": self.cancel_actor}
        )
        return True

    @workflow.run
    async def run(self, data: dict) -> dict:
        run_id = data["run_id"]
        try:
            await self._transition(run_id, "REPRODUCING", "reproducing")
            reproduction = await self._activity(
                "reproduce_incident",
                {
                    "run_id": run_id,
                    "scenario_id": data["scenario_id"],
                    "effect_key": f"run:{run_id}:reproduction",
                },
                long_running=True,
            )
            if await self._stop_if_cancelled(run_id, "after-reproduction"):
                return {"state": "CANCELLED"}

            await self._transition(run_id, "COLLECTING", "collecting")
            await self._activity(
                "collect_evidence_placeholder",
                {
                    "run_id": run_id,
                    "effect_key": f"run:{run_id}:evidence-placeholder",
                    "pinned_commit": data.get("pinned_commit"),
                    "observed_start": reproduction.get("observed_start"),
                    "observed_end": reproduction.get("observed_end"),
                    "request_ids": reproduction.get("request_ids", []),
                },
                timeout_seconds=45,
            )
            if await self._stop_if_cancelled(run_id, "after-collection"):
                return {"state": "CANCELLED"}

            await self._transition(run_id, "DIAGNOSING", "diagnosing")
            await self._activity(
                "diagnose_placeholder",
                {"run_id": run_id, "effect_key": f"run:{run_id}:diagnosis-placeholder"},
                timeout_seconds=45,
            )
            await self._transition(run_id, "AWAITING_REPAIR_APPROVAL", "awaiting-approval")
            await workflow.wait_condition(
                lambda: self.approval is not None or self.cancel_requested
            )
            if await self._stop_if_cancelled(run_id, "awaiting-approval"):
                return {"state": "CANCELLED"}
            if self.approval == "rejected":
                await self._transition(run_id, "CLOSED", "approval-rejected")
                return {"state": "CLOSED"}

            await self._transition(run_id, "GENERATING", "generating")
            await self._activity(
                "generate_repair_placeholder",
                {"run_id": run_id, "effect_key": f"run:{run_id}:repair-placeholder"},
                timeout_seconds=60,
            )
            if await self._stop_if_cancelled(run_id, "after-generation"):
                return {"state": "CANCELLED"}

            await self._transition(run_id, "VERIFYING", "verifying")
            await workflow.wait_condition(
                lambda: self.verification_available or self.cancel_requested
            )
            if await self._stop_if_cancelled(run_id, "awaiting-verification"):
                return {"state": "CANCELLED"}
            verification = await self._activity(
                "finalize_verification",
                {"run_id": run_id, "effect_key": f"run:{run_id}:verification-ranking"},
            )
            terminal_state = verification["terminal_state"]
            if terminal_state != "COMPLETED":
                await self._transition(
                    run_id,
                    terminal_state,
                    "verification-terminal",
                    {
                        "verified_count": verification["verified_count"],
                        "score_version": verification["score_version"],
                    },
                )
                return {"state": terminal_state}

            await self._transition(run_id, "REPORTING", "reporting")
            await self._activity(
                "report_placeholder",
                {"run_id": run_id, "effect_key": f"run:{run_id}:report-placeholder"},
            )
            await self._transition(run_id, "COMPLETED", "completed")
            return {"state": "COMPLETED"}
        except Exception as error:
            await self._transition(
                run_id,
                "FAILED",
                "failed",
                {"failure_category": type(error).__name__},
            )
            raise

    @workflow.signal
    async def repair_approval(self, decision: str) -> None:
        if self.approval is None:
            self.approval = decision

    @workflow.signal
    async def verification_completed(self) -> None:
        self.verification_available = True

    @workflow.signal
    async def request_cancel(self, actor: str) -> None:
        self.cancel_requested = True
        self.cancel_actor = actor

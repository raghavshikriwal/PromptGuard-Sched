"""Persists one job's pipeline outcome to `schedule_decisions` /
`stage_latencies` (blueprint §9 schema, `db/migrations/models.py`).

Kept as its own module rather than inlined in `src/scheduler/pipeline.py`
so the ORM/session details are isolated from orchestration logic — the
same separation `src/encoder/state_encoder.py` argues for in its own
docstring ("No DB I/O ... keeping this module a pure function of its
inputs is what makes it unit-testable in isolation"). `pipeline.py` decides
*when* to persist and with what data; this module only knows *how*.

README §6 rule: ASR/CFD/latency must come from a `SELECT` against these
exact tables — this module's only job is writing rows that satisfy that
contract faithfully (correct `trace_id` linkage, `guard_flagged`/
`anomaly_flagged` left `None` rather than guessed at, since those layers
are not implemented yet — see `src/scheduler/pipeline.py` module docstring).
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from db.migrations.models import ScheduleDecision, StageLatency
from src.config import PipelineStage
from src.ilp.refine import AllocationDecision
from src.llm.client import LLMCandidateResult
from src.scheduler.fairness import RESOURCE_FIELDS, dominant_resource_share
from src.simulator.models import ClusterState, Job


def persist_schedule_decision(
    session: Session,
    *,
    experiment_id: UUID,
    trace_id: UUID,
    job: Job,
    cluster_state: ClusterState,
    llm_result: LLMCandidateResult,
    allocation: AllocationDecision,
    entitlement: float,
) -> ScheduleDecision:
    """Insert one `schedule_decisions` row for a completed pipeline run.

    Does not commit — callers control transaction boundaries (a batch
    experiment run in `eval/experiments/` should commit once per batch,
    not once per job, to keep SQLite/Postgres write throughput reasonable
    under the load tests in blueprint §15).

    Args:
        session: caller-owned SQLAlchemy session. This module never creates
            an engine or session itself (dependency injection — keeps
            `src/scheduler/` free of a hardcoded `database_url`, so tests
            can pass an in-memory SQLite session).
        experiment_id: the `experiments` row this decision belongs to.
        trace_id: threaded through from job submission (blueprint §8 rule
            #2) — must match the `trace_id` used in `stage_latencies` rows
            for this job, which `persist_stage_latencies` below enforces
            by construction (same argument, one call site).
        job, cluster_state: used only to compute `dominant_entitlement`'s
            counterpart, `allocated_share` — the achieved dominant share of
            `allocation.allocated` against `cluster_state`'s capacity.
        llm_result: the LLM stage's output — `llm_result.raw_response` is
            what gets stored, not a re-serialization of `.proposal`
            (matches the "raw output, kept for audit" schema intent).
        allocation: the ILP stage's finalized `AllocationDecision`.
        entitlement: this job's DRF entitlement `e_J`
            (`src/scheduler/fairness.compute_drf_entitlements`), stored as
            `dominant_entitlement` so `delta_j` is computed by the DB's
            generated column, never recomputed ad hoc downstream.
    """
    del job  # total_demand already folded into `allocation`; kept for signature symmetry/future use
    allocated_share = dominant_resource_share(allocation.allocated, cluster_state.total_capacity())

    decision = ScheduleDecision(
        experiment_id=experiment_id,
        job_id=allocation.job_id,
        trace_id=trace_id,
        guard_flagged=None,  # Layer 1 (src/guard/) not yet implemented — blueprint §16 phase 7
        guard_score=None,
        llm_candidate={
            "model_id": llm_result.model_id,
            "attempts": llm_result.attempts,
            "raw_response": llm_result.raw_response,
            "proposal": llm_result.proposal.model_dump(),
        },
        ilp_allocation={
            "allocated_shares": allocation.allocated_shares,
            "proposed_shares": allocation.proposed_shares,
            "objective_value": allocation.objective_value,
            "solver_status": allocation.solver_status,
        },
        anomaly_flagged=None,  # Layer 3 (src/anomaly/) not yet implemented — blueprint §16 phase 8
        dominant_entitlement=entitlement,
        allocated_share=allocated_share,
    )
    session.add(decision)
    return decision


def persist_stage_latencies(
    session: Session,
    *,
    trace_id: UUID,
    latencies_ms: Mapping[PipelineStage, float],
) -> list[StageLatency]:
    """Insert one `stage_latencies` row per stage timed for `trace_id`.

    Args:
        latencies_ms: `PipelineStage -> elapsed milliseconds`, as measured
            by `src/scheduler/pipeline.py` around each stage call. Every
            key must be a `PipelineStage` member (never a bare string —
            README §6 rule), which the DB's own `ck_stage_latencies_stage_valid`
            check constraint also enforces at the storage layer as a second
            line of defense.
    """
    rows = [
        StageLatency(trace_id=trace_id, stage=stage.value, latency_ms=latency_ms)
        for stage, latency_ms in latencies_ms.items()
    ]
    session.add_all(rows)
    return rows


# Re-exported for callers that only need the resource-field ordering
# alongside persistence helpers (avoids an extra import of fairness.py in
# call sites that already import this module).
__all__ = [
    "RESOURCE_FIELDS",
    "persist_schedule_decision",
    "persist_stage_latencies",
]

"""Integration test for `src/scheduler/pipeline.py` (blueprint §15:
"submit a job through the full in-process pipeline, assert it lands in
`schedule_decisions` with correct `trace_id` linkage across
`stage_latencies`").

Uses `DeterministicEchoBackend` (no GPU, no model weights — see that
class's own docstring) and an in-memory SQLite database, so this test has
no external dependencies and runs in CI (`.github/workflows/ci.yml`).
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.migrations.models import Base, Experiment, Job as JobRow, ScheduleDecision, StageLatency
from db.migrations.models import Tenant as TenantRow
from src.config import DefenseConfig, PipelineStage
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner
from src.llm.backends import DeterministicEchoBackend
from src.llm.client import LLMCandidateGenerator
from src.scheduler.fairness import compute_delta_j, dominant_resource_share
from src.scheduler.pipeline import SchedulingPipeline
from src.simulator.models import ClusterState, Job, NodeCapacity, ResourceDemand, Task


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def job() -> Job:
    return Job(
        tenant_id=uuid4(),
        description="run a batch report",
        weight=1.0,
        tasks=(
            Task(
                task_name="aggregate",
                demand=ResourceDemand(cpu=4.0, mem_gb=8.0, disk_gb=0.0, net_mbps=0.0),
                est_duration_s=120,
            ),
        ),
    )


@pytest.fixture
def cluster_state() -> ClusterState:
    return ClusterState(
        observed_at_s=0,
        nodes=(
            NodeCapacity(
                zone="zone-a",
                capacity=ResourceDemand(cpu=16.0, mem_gb=32.0, disk_gb=100.0, net_mbps=1000.0),
            ),
        ),
    )


@pytest.fixture
def pipeline() -> SchedulingPipeline:
    return SchedulingPipeline(
        encoder=TrustAwareStateEncoder(),
        llm_generator=LLMCandidateGenerator(DeterministicEchoBackend(seed=42)),
        ilp_refiner=IlpAllocationRefiner(),
    )


def _seed_job_and_experiment(session: Session, job: Job) -> Experiment:
    """Insert the `tenants` / `jobs` / `experiments` rows a real
    `schedule_decisions` row's foreign keys point at, so this test exercises
    the same referential shape a real experiment run would produce.
    """
    session.add(TenantRow(tenant_id=job.tenant_id, name="test-tenant"))
    session.add(
        JobRow(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            priority=job.priority,
            deadline_s=job.deadline_s,
            weight=job.weight,
            description=job.description,
        )
    )
    experiment = Experiment(
        defense_config=DefenseConfig.NONE.value,
        model_id=DeterministicEchoBackend(seed=42).model_id,
        injection_ratio=0.0,
        random_seed=42,
    )
    session.add(experiment)
    session.flush()
    return experiment


class TestSchedulingPipelineIntegration:
    def test_job_lands_in_schedule_decisions_with_linked_stage_latencies(
        self, session: Session, pipeline: SchedulingPipeline, job: Job, cluster_state: ClusterState
    ) -> None:
        experiment = _seed_job_and_experiment(session, job)

        outcome = pipeline.schedule_and_persist(
            session,
            experiment_id=experiment.experiment_id,
            job=job,
            cluster_state=cluster_state,
            defense_config=DefenseConfig.NONE,
        )
        session.commit()

        decision = session.execute(
            select(ScheduleDecision).where(ScheduleDecision.job_id == job.job_id)
        ).scalar_one()
        assert decision.trace_id == outcome.trace_id
        assert decision.experiment_id == experiment.experiment_id
        assert decision.guard_flagged is None  # guard layer not implemented yet
        assert decision.anomaly_flagged is None  # anomaly layer not implemented yet

        latency_rows = session.execute(
            select(StageLatency).where(StageLatency.trace_id == outcome.trace_id)
        ).scalars().all()
        assert {row.stage for row in latency_rows} == {
            PipelineStage.ENCODE.value,
            PipelineStage.LLM.value,
            PipelineStage.ILP.value,
        }
        assert all(row.latency_ms >= 0.0 for row in latency_rows)

    def test_delta_j_is_internally_consistent(
        self, pipeline: SchedulingPipeline, job: Job, cluster_state: ClusterState
    ) -> None:
        """Whatever Δ(J) the pipeline returns must equal what
        `compute_delta_j` gives when fed the outcome's own entitlement and
        achieved dominant share — a regression guard against the
        orchestrator silently diverging from the formula it wraps.
        """
        outcome = pipeline.schedule_job(job=job, cluster_state=cluster_state, defense_config=DefenseConfig.NONE)

        achieved_share = dominant_resource_share(outcome.allocation.allocated, cluster_state.total_capacity())
        expected_delta_j = compute_delta_j(achieved_share, outcome.entitlement)

        assert outcome.delta_j == expected_delta_j

    def test_active_jobs_must_include_the_scheduled_job(
        self, pipeline: SchedulingPipeline, job: Job, cluster_state: ClusterState
    ) -> None:
        other_job = Job(
            tenant_id=uuid4(),
            tasks=(
                Task(
                    task_name="other",
                    demand=ResourceDemand(cpu=1.0, mem_gb=1.0, disk_gb=0.0, net_mbps=0.0),
                    est_duration_s=10,
                ),
            ),
        )
        with pytest.raises(ValueError, match="active_jobs must include"):
            pipeline.schedule_job(
                job=job,
                cluster_state=cluster_state,
                defense_config=DefenseConfig.NONE,
                active_jobs=(other_job,),
            )

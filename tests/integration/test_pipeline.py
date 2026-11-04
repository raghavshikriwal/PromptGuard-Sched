"""Integration tests for src/scheduler/pipeline.py.

Covers:
- Persistence and trace_id linkage across stage_latencies.
- Delta(J) calculation consistency.
- Anomaly-cap enforcement against an adversarial LLM proposal.
- active_jobs validation.
- Multi-job capacity accounting.

Uses deterministic test backends and in-memory SQLite. No GPU or model
weights are required.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from db.migrations.models import Base, Experiment, ScheduleDecision, StageLatency
from db.migrations.models import Job as JobRow
from db.migrations.models import Tenant as TenantRow
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from src.config import DefenseConfig, PipelineStage
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner
from src.llm.backends import DeterministicEchoBackend
from src.llm.client import LLMCandidateGenerator
from src.scheduler.capacity import CapacityLedger
from src.scheduler.fairness import compute_delta_j, dominant_resource_share
from src.scheduler.pipeline import SchedulingPipeline
from src.simulator.models import (
    ClusterState,
    Job,
    NodeCapacity,
    ResourceDemand,
    Task,
)


class OverAllocationBackend:
    """Deterministic adversarial backend for anomaly-cap regression tests."""

    @property
    def model_id(self) -> str:
        return "test-over-allocation-backend"

    def generate(
        self,
        prompt: str,
        *,
        max_new_tokens: int = 256,
    ) -> str:
        return (
            '{"cpu_share": 1.0, "mem_share": 1.0, '
            '"disk_share": 1.0, "net_share": 1.0, '
            '"rationale": "deliberately requests full allocation"}'
        )


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
                demand=ResourceDemand(
                    cpu=4.0,
                    mem_gb=8.0,
                    disk_gb=0.0,
                    net_mbps=0.0,
                ),
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
                capacity=ResourceDemand(
                    cpu=16.0,
                    mem_gb=32.0,
                    disk_gb=100.0,
                    net_mbps=1000.0,
                ),
            ),
        ),
    )


@pytest.fixture
def pipeline() -> SchedulingPipeline:
    return SchedulingPipeline(
        encoder=TrustAwareStateEncoder(),
        llm_generator=LLMCandidateGenerator(
            DeterministicEchoBackend(seed=42)
        ),
        ilp_refiner=IlpAllocationRefiner(),
    )


def _seed_job_and_experiment(session: Session, job: Job) -> Experiment:
    """Insert the tenants/jobs/experiments rows referenced by a decision."""
    session.add(
        TenantRow(
            tenant_id=job.tenant_id,
            name="test-tenant",
        )
    )
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
        self,
        session: Session,
        pipeline: SchedulingPipeline,
        job: Job,
        cluster_state: ClusterState,
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
            select(ScheduleDecision).where(
                ScheduleDecision.job_id == job.job_id
            )
        ).scalar_one()

        assert decision.trace_id == outcome.trace_id
        assert decision.experiment_id == experiment.experiment_id
        assert decision.guard_flagged is None
        assert decision.anomaly_flagged is None

        latency_rows = (
            session.execute(
                select(StageLatency).where(
                    StageLatency.trace_id == outcome.trace_id
                )
            )
            .scalars()
            .all()
        )

        assert {row.stage for row in latency_rows} == {
            PipelineStage.ENCODE.value,
            PipelineStage.LLM.value,
            PipelineStage.ILP.value,
        }
        assert all(row.latency_ms >= 0.0 for row in latency_rows)

    def test_delta_j_is_internally_consistent(
        self,
        pipeline: SchedulingPipeline,
        job: Job,
        cluster_state: ClusterState,
    ) -> None:
        """The returned delta must match the fairness formula."""
        outcome = pipeline.schedule_job(
            job=job,
            cluster_state=cluster_state,
            defense_config=DefenseConfig.NONE,
        )

        achieved_share = dominant_resource_share(
            outcome.allocation.allocated,
            cluster_state.total_capacity(),
        )
        expected_delta_j = compute_delta_j(
            achieved_share,
            outcome.entitlement,
        )

        assert outcome.delta_j == expected_delta_j

    def test_adversarial_proposal_is_flagged_and_final_allocation_is_capped(
        self,
        session: Session,
        job: Job,
        cluster_state: ClusterState,
    ) -> None:
        """A full-allocation attack must be detected and capped after ILP."""

        adversarial_pipeline = SchedulingPipeline(
            encoder=TrustAwareStateEncoder(),
            llm_generator=LLMCandidateGenerator(
                OverAllocationBackend()
            ),
            ilp_refiner=IlpAllocationRefiner(),
        )

        # Five competitors plus the target create six identical jobs.
        # Their combined demand saturates CPU and memory before each
        # job receives its full requested allocation.
        competitors = tuple(
            Job(
                tenant_id=uuid4(),
                weight=1.0,
                tasks=(
                    Task(
                        task_name=f"competitor-{index}",
                        demand=ResourceDemand(
                            cpu=4.0,
                            mem_gb=8.0,
                            disk_gb=0.0,
                            net_mbps=0.0,
                        ),
                        est_duration_s=120,
                    ),
                ),
            )
            for index in range(5)
        )
        active_jobs = (job, *competitors)

        experiment = _seed_job_and_experiment(session, job)

        outcome = adversarial_pipeline.schedule_and_persist(
            session,
            experiment_id=experiment.experiment_id,
            job=job,
            cluster_state=cluster_state,
            defense_config=DefenseConfig.ILP_ANOMALY_ONLY,
            active_jobs=active_jobs,
        )

        # Confirm the adversarial proposal was actually detected.
        assert outcome.anomaly_result is not None
        assert outcome.anomaly_result.flagged is True

        # For six identical jobs, entitlement should be approximately
        # 1/6 of the target's full-demand dominant share (0.25).
        assert outcome.entitlement == pytest.approx(
            1.0 / 6.0,
            abs=1e-8,
        )

        # The uncapped full-demand proposal has delta(J) approximately
        # 0.50, which is above the configured 0.25 threshold.
        assert outcome.anomaly_result.proposed_delta_j == pytest.approx(
            0.50,
            abs=1e-8,
        )

        # Verify that the anomaly checker capped its proposal.
        capped_proposal = outcome.anomaly_result.proposal
        total_demand = job.total_demand()

        capped_demand = ResourceDemand(
            cpu=capped_proposal.cpu_share * total_demand.cpu,
            mem_gb=capped_proposal.mem_share * total_demand.mem_gb,
            disk_gb=capped_proposal.disk_share * total_demand.disk_gb,
            net_mbps=capped_proposal.net_share * total_demand.net_mbps,
        )

        capped_share = dominant_resource_share(
            capped_demand,
            cluster_state.total_capacity(),
        )

        assert capped_share <= outcome.entitlement * 1.25

        # Verify that ILP did not raise the final allocation above the cap.
        achieved_share = dominant_resource_share(
            outcome.allocation.allocated,
            cluster_state.total_capacity(),
        )

        assert outcome.delta_j is not None
        assert outcome.delta_j <= 0.25
        assert achieved_share <= outcome.entitlement * 1.25

        # Verify SQLite's generated delta_j using the raw stored value.
        session.commit()
        persisted_delta = session.connection().exec_driver_sql(
            "SELECT delta_j FROM schedule_decisions"
        ).scalar_one()

        assert persisted_delta is not None
        assert float(persisted_delta) <= 0.25

    def test_active_jobs_must_include_the_scheduled_job(
        self,
        pipeline: SchedulingPipeline,
        job: Job,
        cluster_state: ClusterState,
    ) -> None:
        other_job = Job(
            tenant_id=uuid4(),
            tasks=(
                Task(
                    task_name="other",
                    demand=ResourceDemand(
                        cpu=1.0,
                        mem_gb=1.0,
                        disk_gb=0.0,
                        net_mbps=0.0,
                    ),
                    est_duration_s=10,
                ),
            ),
        )

        with pytest.raises(
            ValueError,
            match="active_jobs must include",
        ):
            pipeline.schedule_job(
                job=job,
                cluster_state=cluster_state,
                defense_config=DefenseConfig.NONE,
                active_jobs=(other_job,),
            )


class TestMultiJobCapacityAccounting:

    def test_jobs_sharing_a_ledger_never_allocate_more_than_the_cluster_has(
        self,
        pipeline: SchedulingPipeline,
        cluster_state: ClusterState,
    ) -> None:
        tenant_id = uuid4()

        jobs = tuple(
            Job(
                tenant_id=tenant_id,
                tasks=(
                    Task(
                        task_name=f"task-{index}",
                        demand=ResourceDemand(
                            cpu=10.0,
                            mem_gb=20.0,
                            disk_gb=0.0,
                            net_mbps=0.0,
                        ),
                        est_duration_s=60,
                    ),
                ),
            )
            for index in range(3)
        )

        ledger = CapacityLedger.from_cluster(cluster_state)
        total = cluster_state.total_capacity()

        outcomes = [
            pipeline.schedule_job(
                job=current_job,
                cluster_state=cluster_state,
                defense_config=DefenseConfig.NONE,
                active_jobs=jobs,
                capacity_ledger=ledger,
            )
            for current_job in jobs
        ]

        assert (
            sum(o.allocation.allocated.cpu for o in outcomes)
            <= total.cpu + 1e-6
        )
        assert (
            sum(o.allocation.allocated.mem_gb for o in outcomes)
            <= total.mem_gb + 1e-6
        )
        assert ledger.remaining.cpu == pytest.approx(
            total.cpu
            - sum(o.allocation.allocated.cpu for o in outcomes),
            abs=1e-6,
        )

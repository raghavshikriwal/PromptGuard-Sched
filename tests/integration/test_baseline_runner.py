"""Integration tests for `eval/experiments/baseline_runner.py` and
`compute_baseline_metrics`, against an in-memory SQLite database and the
deterministic echo backend (no GPU, no model weights).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from db.migrations.models import Base, Experiment, ScheduleDecision
from eval.experiments.baseline_runner import (
    BaselineExperimentRunner,
    BaselineRunnerError,
    BaselineRunResult,
)
from eval.metrics.baseline_metrics import BaselineMetricsError, compute_baseline_metrics
from src.config import DefenseConfig
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner
from src.llm.backends import DeterministicEchoBackend, LLMBackend
from src.llm.client import LLMCandidateGenerator
from src.simulator.cluster_generator import size_cluster_for_target_utilization, total_job_demand
from src.simulator.models import ClusterState, Job, NodeCapacity, ResourceDemand
from src.simulator.trace_loader import SyntheticTraceGenerator

_NUM_JOBS = 8
_SEED = 0


class _BrokenBackend:
    """Never returns schema-valid JSON, so every job fails at the LLM stage."""

    model_id = "broken/model"

    def generate(self, prompt: str, *, max_new_tokens: int = 256) -> str:
        return "not json"


def _runner(backend: LLMBackend) -> BaselineExperimentRunner:
    return BaselineExperimentRunner(
        encoder=TrustAwareStateEncoder(),
        llm_generator=LLMCandidateGenerator(backend),
        ilp_refiner=IlpAllocationRefiner(),
    )


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def jobs() -> list[Job]:
    return SyntheticTraceGenerator(seed=_SEED).generate(_NUM_JOBS)


@pytest.fixture
def cluster(jobs: list[Job]) -> ClusterState:
    return size_cluster_for_target_utilization(jobs, target_utilization=0.766, num_nodes=4)


def _run(session: Session, jobs: list[Job], cluster: ClusterState) -> BaselineRunResult:
    return _runner(DeterministicEchoBackend(seed=_SEED)).run(
        session,
        jobs=jobs,
        cluster_state=cluster,
        defense_config=DefenseConfig.NONE,
        random_seed=_SEED,
        allow_echo_backend=True,
    )


def _decision_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(ScheduleDecision)).scalar_one()


class TestBaselineExperimentRunner:
    def test_run_persists_one_decision_per_job(
        self, session: Session, jobs: list[Job], cluster: ClusterState
    ) -> None:
        result = _run(session, jobs, cluster)

        assert result.jobs_failed == ()
        assert len(result.jobs_succeeded) == _NUM_JOBS
        assert _decision_count(session) == _NUM_JOBS
        experiment = session.get(Experiment, result.experiment_id)
        assert experiment is not None
        assert experiment.finished_at is not None
        assert experiment.model_id.startswith("echo-test/")

    def test_echo_backend_is_refused_without_acknowledgement(
        self, session: Session, jobs: list[Job], cluster: ClusterState
    ) -> None:
        with pytest.raises(BaselineRunnerError, match="refusing"):
            _runner(DeterministicEchoBackend(seed=_SEED)).run(
                session,
                jobs=jobs,
                cluster_state=cluster,
                defense_config=DefenseConfig.NONE,
                random_seed=_SEED,
            )

    def test_empty_job_set_is_rejected(self, session: Session, cluster: ClusterState) -> None:
        with pytest.raises(BaselineRunnerError, match="empty"):
            _run(session, [], cluster)

    def test_same_job_set_can_be_run_twice_in_one_database(
        self, session: Session, jobs: list[Job], cluster: ClusterState
    ) -> None:
        """Paired C0..C4 comparisons reuse one job set; ids are deterministic,
        so seeding must skip rows that already exist rather than collide.
        """
        first = _run(session, jobs, cluster)
        second = _run(session, jobs, cluster)

        assert first.experiment_id != second.experiment_id
        assert _decision_count(session) == 2 * _NUM_JOBS

    def test_every_job_failing_is_recorded_not_raised(
        self, session: Session, jobs: list[Job], cluster: ClusterState
    ) -> None:
        result = _runner(_BrokenBackend()).run(
            session,
            jobs=jobs,
            cluster_state=cluster,
            defense_config=DefenseConfig.NONE,
            random_seed=_SEED,
        )

        assert len(result.jobs_failed) == _NUM_JOBS
        assert result.jobs_succeeded == ()
        assert {failure.exception_type for failure in result.jobs_failed} == {"LLMCandidateError"}
        assert _decision_count(session) == 0

    def test_contended_batch_never_allocates_more_cpu_than_the_cluster_has(
        self, session: Session, jobs: list[Job]
    ) -> None:
        demand = total_job_demand(jobs)
        scarce = ClusterState(
            observed_at_s=0,
            nodes=(
                NodeCapacity(
                    zone="zone-a",
                    capacity=ResourceDemand(
                        cpu=demand.cpu / 2,
                        mem_gb=demand.mem_gb / 2,
                        disk_gb=demand.disk_gb / 2,
                        net_mbps=demand.net_mbps / 2,
                    ),
                ),
            ),
        )

        result = _run(session, jobs, scarce)

        allocated_cpu = 0.0
        demand_by_job_id = {job.job_id: job.total_demand() for job in jobs}
        for decision in session.execute(
            select(ScheduleDecision).where(ScheduleDecision.experiment_id == result.experiment_id)
        ).scalars():
            share = decision.ilp_allocation["allocated_shares"]["cpu"]
            allocated_cpu += share * demand_by_job_id[decision.job_id].cpu

        assert allocated_cpu <= scarce.total_capacity().cpu + 1e-6


class TestComputeBaselineMetrics:
    def test_metrics_are_well_formed(
        self, session: Session, jobs: list[Job], cluster: ClusterState
    ) -> None:
        result = _run(session, jobs, cluster)

        metrics = compute_baseline_metrics(
            session,
            experiment_id=result.experiment_id,
            jobs=list(result.jobs_succeeded),
            cluster_state=cluster,
        )

        assert metrics.jobs_evaluated == _NUM_JOBS
        assert metrics.avg_jct_s > 0.0
        assert 0.0 <= metrics.cpu_utilization <= 1.0
        assert 0.0 <= metrics.sla_violation_rate <= 1.0
        assert 0.0 < metrics.drf_fairness_index <= 1.0

    def test_null_ilp_allocation_raises(
        self, session: Session, jobs: list[Job], cluster: ClusterState
    ) -> None:
        result = _run(session, jobs, cluster)
        decision = session.execute(
            select(ScheduleDecision).where(ScheduleDecision.experiment_id == result.experiment_id)
        ).scalars().first()
        assert decision is not None
        decision.ilp_allocation = None
        session.commit()

        with pytest.raises(BaselineMetricsError, match="ilp_allocation is NULL"):
            compute_baseline_metrics(
                session,
                experiment_id=result.experiment_id,
                jobs=list(result.jobs_succeeded),
                cluster_state=cluster,
            )

    def test_job_without_a_decision_row_raises(
        self, session: Session, jobs: list[Job], cluster: ClusterState
    ) -> None:
        result = _run(session, jobs, cluster)
        stranger = SyntheticTraceGenerator(seed=99).generate(1)

        with pytest.raises(BaselineMetricsError, match="no schedule_decisions row"):
            compute_baseline_metrics(
                session,
                experiment_id=result.experiment_id,
                jobs=[*result.jobs_succeeded, *stranger],
                cluster_state=cluster,
            )

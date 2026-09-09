"""Baseline experiment runner — blueprint §13, the mandatory gate.

This is the module `eval/metrics/baseline_metrics.py` already imports from
(`critical_path_duration_s`) and the piece README §4 describes as
"replays a benign job set through the `defense_config=none` pipeline and
persists it." It did not exist yet; this file is that missing piece.

Scheduling model: single window. This runner does not replay a trace over
simulated time or model job arrival order — it takes one job set and one
`ClusterState` snapshot, treats every job in the set as concurrently
active for DRF entitlement purposes (`active_jobs=job_tuple` on every
`SchedulingPipeline.schedule_job` call), and schedules each job against
that same shared snapshot. That is the "simplified single-window
scheduling model" `baseline_metrics.py`'s module docstring points back
here for. A full multi-window trace replay (jobs arriving and leaving
over simulated time) is later `eval/experiments/` work, not required for
the blueprint §13 gate itself.

Two things this module is deliberately NOT:
- Not an attack runner. `injection_ratio` on the persisted `Experiment`
  row is derived from whatever `is_synthetic_attack` labels the caller's
  job set already carries — this module never decides injection ratios
  or reads `eval/attacks/` (blueprint §13: "Do not build attack ...
  code before that gate passes"). The gate itself should always be run
  against an all-benign job set (`injection_ratio == 0.0`).
- Not a metrics module. It persists `schedule_decisions` rows and reports
  which jobs failed; `eval/metrics/baseline_metrics.py` reads those rows
  back and computes Avg-JCT/utilization/SVR/DRF-fairness against the
  LLMSched reference. Kept separate so "did the run complete" and "what
  do the numbers say" stay independently inspectable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import networkx as nx
from sqlalchemy.orm import Session

from db.migrations.models import Experiment
from db.migrations.models import Job as JobRow
from db.migrations.models import Tenant as TenantRow
from src.config import DefenseConfig
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner, IlpRefinementError
from src.llm.backends import ECHO_MODEL_ID_PREFIX
from src.llm.client import LLMCandidateError, LLMCandidateGenerator
from src.scheduler.fairness import DrfEntitlementError
from src.scheduler.pipeline import SchedulingPipeline
from src.simulator.models import ClusterState, Job

# Per-job failures we treat as measurable pipeline outcomes worth recording
# and continuing past, matching the rationale already stated in
# `src/llm/client.py` (`LLMCandidateError`: "a model's inability to follow
# the schema is itself a measurable outcome") and `src/ilp/refine.py`
# (`IlpRefinementError`: infeasible-or-solver-failure). A `ValueError` from
# `SchedulingPipeline`'s own `active_jobs` sanity check is deliberately
# NOT caught here — this runner always passes the full batch as
# `active_jobs`, so that check should never fire; if it does, that is a
# bug in this module, not a per-job experimental outcome, and should crash
# loudly rather than be swallowed into a metrics report.
_RECORDED_FAILURE_TYPES = (LLMCandidateError, IlpRefinementError, DrfEntitlementError)


class BaselineRunnerError(RuntimeError):
    """Raised for caller errors this runner refuses to proceed past —
    an empty job set, or an attempt to run against
    `DeterministicEchoBackend` without explicitly acknowledging it (see
    `BaselineExperimentRunner.run`'s `allow_echo_backend` argument).
    """


@dataclass(frozen=True, slots=True)
class JobFailure:
    """One job's pipeline run failed and was excluded from persistence.

    Recorded rather than silently dropped so `BaselineMetricsError`'s own
    advice ("investigate `jobs_failed` ... before trusting this
    experiment's metrics") has something concrete to point at.
    """

    job_id: UUID
    exception_type: str
    error: str


@dataclass(frozen=True, slots=True)
class BaselineRunResult:
    """Everything a caller (the gate CLI, or `eval/metrics/baseline_metrics.py`
    indirectly via its docstring references) needs from one baseline run.
    """

    experiment_id: UUID
    defense_config: DefenseConfig
    model_id: str
    random_seed: int
    injection_ratio: float
    cluster_state: ClusterState
    jobs: tuple[Job, ...]
    jobs_failed: tuple[JobFailure, ...]

    @property
    def jobs_succeeded(self) -> tuple[Job, ...]:
        """The subset of `jobs` that has a `schedule_decisions` row —
        i.e. the only job set it is valid to pass to
        `compute_baseline_metrics` (blueprint §13/§9 reproducibility rule:
        that function raises rather than silently excluding a mismatch).
        """
        failed_ids = {failure.job_id for failure in self.jobs_failed}
        return tuple(job for job in self.jobs if job.job_id not in failed_ids)


def critical_path_duration_s(job: Job) -> float:
    """Length, in seconds, of the longest dependency chain in `job`'s task DAG.

    Standard critical-path-method earliest-finish-time computation over
    `job.to_networkx()`: a task with no predecessors can start at t=0; any
    other task can start only once every predecessor has finished. The
    job's overall duration (at share=1.0, i.e. full demand granted) is the
    latest of any task's finish time — independent tasks with no
    dependency between them are assumed schedulable in parallel, not
    summed serially, which is what makes this a *critical path* length
    rather than a sum of every task's duration.

    `eval/metrics/baseline_metrics.py` divides this by a job's achieved
    bottleneck resource share to get that job's JCT (blueprint §11
    Avg-JCT figure) — see that module's `compute_baseline_metrics`.

    A job always has at least one task (`Job.tasks` has `min_length=1`),
    so this never operates on an empty DAG.
    """
    graph = job.to_networkx()
    duration_by_task_id = {task.task_id: float(task.est_duration_s) for task in job.tasks}

    earliest_finish_s: dict[UUID, float] = {}
    for task_id in nx.topological_sort(graph):
        start_s = max(
            (earliest_finish_s[predecessor] for predecessor in graph.predecessors(task_id)),
            default=0.0,
        )
        earliest_finish_s[task_id] = start_s + duration_by_task_id[task_id]

    return max(earliest_finish_s.values())


class BaselineExperimentRunner:
    """Replays a job set through the pipeline once, as one concurrent batch,
    and persists an `experiments` row plus one `schedule_decisions` row
    per successfully-scheduled job.

    Composes the same three stage classes `SchedulingPipeline` does
    (rather than accepting a pre-built pipeline) so this class can read
    `llm_generator.model_id` directly for the `experiments.model_id`
    column — `SchedulingPipeline` itself does not expose that publicly,
    by design (it only needs to pass calls through, not report on them).
    """

    def __init__(
        self,
        *,
        encoder: TrustAwareStateEncoder,
        llm_generator: LLMCandidateGenerator,
        ilp_refiner: IlpAllocationRefiner,
    ) -> None:
        self._llm_generator = llm_generator
        self._pipeline = SchedulingPipeline(
            encoder=encoder, llm_generator=llm_generator, ilp_refiner=ilp_refiner
        )

    @property
    def model_id(self) -> str:
        return self._llm_generator.model_id

    def run(
        self,
        session: Session,
        *,
        jobs: Sequence[Job],
        cluster_state: ClusterState,
        defense_config: DefenseConfig,
        random_seed: int,
        allow_echo_backend: bool = False,
    ) -> BaselineRunResult:
        """Schedule every job in `jobs` against `cluster_state` and persist
        the run as one `experiments` row.

        Args:
            session: caller-owned SQLAlchemy session. Committed once at
                the end of this call (blueprint §9 / `persist_schedule_decision`
                docstring: "a batch experiment run ... should commit once
                per batch, not once per job").
            jobs: the full concurrent batch — passed as `active_jobs` to
                every single-job `SchedulingPipeline` call, so each job's
                DRF entitlement is computed relative to the whole set, not
                to itself alone. Must be non-empty.
            cluster_state: the shared cluster snapshot every job in `jobs`
                competes against — typically sized against this same job
                set's aggregate demand via
                `src.simulator.cluster_generator.size_cluster_for_target_utilization`
                so the gate's CPU-utilization comparison is meaningful.
            defense_config: which C0-C4 cell to run. Blueprint §13's gate
                itself must always be called with `DefenseConfig.NONE` —
                this method does not default or assume that, per the
                project's own rule (blueprint §8 rule #1 / `src/scheduler/
                pipeline.py`'s docstring: never a default baked in here).
            random_seed: recorded on the `experiments` row for reproducibility.
            allow_echo_backend: must be explicitly `True` to run against
                `DeterministicEchoBackend`. Defaults to `False` — refusing
                by default is the behavior `src/llm/backends.py`'s own
                module docstring asks `eval/experiments/` to enforce: an
                echo-backend run is a pipeline-mechanics smoke test, never
                a real gate result, and its `model_id` should never be
                mistaken for one in a stored `Experiment` row without that
                being an explicit, visible choice.

        Raises:
            BaselineRunnerError: `jobs` is empty, or the backend is an
                echo backend and `allow_echo_backend` was not set.

        Returns:
            A `BaselineRunResult`. Check `.jobs_failed` before trusting
            `.jobs_succeeded` represents the whole batch — a run with
            failures still returns normally rather than raising, since a
            partial batch is itself a measurable outcome.
        """
        if not jobs:
            raise BaselineRunnerError("cannot run a baseline experiment against an empty job set")
        if self.model_id.startswith(ECHO_MODEL_ID_PREFIX) and not allow_echo_backend:
            raise BaselineRunnerError(
                f"refusing to run against model_id={self.model_id!r} — this is "
                "DeterministicEchoBackend, a pipeline-mechanics smoke test that does not "
                "read tenant text or real demand ratios (see src/llm/backends.py). Its "
                "output is not a valid blueprint §13 gate result. Pass "
                "allow_echo_backend=True if a mechanics-only smoke test is what you want, "
                "and do not evaluate the result against the LLMSched reference."
            )

        job_tuple = tuple(jobs)
        injection_ratio = sum(1 for job in job_tuple if job.is_synthetic_attack) / len(job_tuple)
        experiment_id = uuid4()

        _seed_tenants_and_jobs(session, job_tuple)
        experiment_row = Experiment(
            experiment_id=experiment_id,
            defense_config=defense_config.value,
            model_id=self.model_id,
            injection_ratio=injection_ratio,
            random_seed=random_seed,
        )
        session.add(experiment_row)

        failures: list[JobFailure] = []
        for job in job_tuple:
            try:
                self._pipeline.schedule_and_persist(
                    session,
                    experiment_id=experiment_id,
                    job=job,
                    cluster_state=cluster_state,
                    defense_config=defense_config,
                    active_jobs=job_tuple,
                )
            except _RECORDED_FAILURE_TYPES as exc:
                failures.append(
                    JobFailure(job_id=job.job_id, exception_type=type(exc).__name__, error=str(exc))
                )

        experiment_row.finished_at = datetime.now(timezone.utc)
        session.commit()

        return BaselineRunResult(
            experiment_id=experiment_id,
            defense_config=defense_config,
            model_id=self.model_id,
            random_seed=random_seed,
            injection_ratio=injection_ratio,
            cluster_state=cluster_state,
            jobs=job_tuple,
            jobs_failed=tuple(failures),
        )


def _seed_tenants_and_jobs(session: Session, jobs: Sequence[Job]) -> None:
    """Insert the `tenants` / `jobs` rows `schedule_decisions.job_id`'s
    foreign key points at, mirroring `tests/integration/test_pipeline.py`'s
    `_seed_job_and_experiment` pattern at batch scale.

    `Job.tenant_id` values are commonly reused across many jobs in one
    batch (`SyntheticTraceGenerator` deliberately draws from a small
    tenant pool) — deduplicated here so a shared tenant is inserted once,
    not once per job. Re-running this against a *persistent* database with
    a job set that reuses `job_id`/`tenant_id` values from an earlier run
    is out of scope: those ids are fresh UUIDs per `Job`/generator
    instantiation by construction, so a collision would indicate the
    caller deliberately replayed the same domain objects — their call to
    make, not this function's to silently paper over.
    """
    seen_tenant_ids: set[UUID] = set()
    for job in jobs:
        if job.tenant_id not in seen_tenant_ids:
            session.add(TenantRow(tenant_id=job.tenant_id, name=f"tenant-{job.tenant_id.hex[:8]}"))
            seen_tenant_ids.add(job.tenant_id)
        session.add(
            JobRow(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                priority=job.priority,
                deadline_s=job.deadline_s,
                weight=job.weight,
                description=job.description,
                is_synthetic_attack=job.is_synthetic_attack,
                attack_payload_type=(
                    job.attack_payload_type.value if job.attack_payload_type is not None else None
                ),
            )
        )


__all__ = [
    "BaselineExperimentRunner",
    "BaselineRunResult",
    "BaselineRunnerError",
    "JobFailure",
    "critical_path_duration_s",
]
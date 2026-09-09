"""Baseline validation metrics — blueprint §13, the mandatory gate.

Computes the four figures the baseline gate compares against the LLMSched
reference (blueprint §11: Avg-JCT 417.9s, CPU utilization 76.6%, SLA
violation rate 11.9%, DRF fairness 0.823) from persisted
`schedule_decisions` rows, per the reproducibility rule in blueprint §9 /
README §6 ("ASR, CFD, and latency numbers must come from a SELECT ...
never from a notebook or a hand-copied number"). The same discipline
applies here even though this is Phase 5, not the attack-metrics work of
Phase 6 — a baseline gate that isn't itself reproducible would undermine
every later measurement built on top of it.

Two things this module is NOT:
- Not a general query library for `eval/metrics/`'s later ASR/CFD work
  (blueprint §12). Those metrics read ground-truth attack labels this
  module never touches (blueprint §13: "Do not build attack ... code
  before that gate passes") — kept in a separate module once Phase 6
  starts, not bolted onto this one.
- Not a statistics module. `eval/statistics/` (blueprint §16, Phase 10)
  owns confidence intervals and paired significance tests; this module
  reports point estimates only, appropriate for a single-run gate check,
  not the seeded, multi-run comparisons later phases require.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.migrations.models import ScheduleDecision
from eval.experiments.baseline_runner import critical_path_duration_s
from src.config import (
    BASELINE_REFERENCE_AVG_JCT_S,
    BASELINE_REFERENCE_CPU_UTILIZATION,
    BASELINE_REFERENCE_DRF_FAIRNESS,
    BASELINE_REFERENCE_SLA_VIOLATION_RATE,
)
from src.scheduler.fairness import RESOURCE_FIELDS
from src.simulator.models import ClusterState, Job, ResourceDemand

# "Directional consistency" (blueprint §13), not exact reproduction — the
# 2011 trace and this project's simplified single-window scheduling model
# (see baseline_runner.py's module docstring) are never going to hit the
# LLMSched reference numbers exactly, nor should the gate pretend they will
# (blueprint §11: "frame results as relative attack/defense effects").
# A relative tolerance band, applied uniformly, keeps the gate an explicit,
# auditable threshold rather than an eyeballed judgment call re-made by
# whoever runs it.
_RELATIVE_TOLERANCE: float = 0.40

_MIN_BOTTLENECK_SHARE: float = 1e-6  # guards JCT division by ~0 allocated share


class BaselineMetricsError(RuntimeError):
    """Raised when the persisted data needed for a metric is missing or
    inconsistent — e.g. a job in `jobs` with no matching `ScheduleDecision`
    row for `experiment_id`, which means the run failed for that job and
    should be investigated, not silently excluded from an average.
    """


@dataclass(frozen=True, slots=True)
class BaselineMetrics:
    """Point-estimate figures for one baseline run — the left-hand side of
    the blueprint §13 gate comparison.
    """

    experiment_id: UUID
    jobs_evaluated: int
    avg_jct_s: float
    cpu_utilization: float
    sla_violation_rate: float
    drf_fairness_index: float
    jobs_with_deadline: int


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One metric's observed value against its LLMSched reference."""

    name: str
    observed: float
    reference: float
    relative_tolerance: float
    within_tolerance: bool


@dataclass(frozen=True, slots=True)
class BaselineGateReport:
    """The blueprint §13 gate's verdict: pass only if every comparison passes.

    `passed` is derived, not independently settable, so a caller can never
    construct a report that disagrees with its own `comparisons` — the
    single failure mode this gate exists to prevent is a human eyeballing
    "close enough" past a metric that actually failed.
    """

    comparisons: tuple[MetricComparison, ...]

    @property
    def passed(self) -> bool:
        return all(comparison.within_tolerance for comparison in self.comparisons)

    def render(self) -> str:
        """Human-readable report for CLI output — the artifact a run of
        `eval/experiments/run_baseline_gate.py` prints and a reviewer or
        the paper's §8 baseline-validation table can be built from.
        """
        lines = [f"Baseline validation gate: {'PASS' if self.passed else 'FAIL'}", ""]
        for comparison in self.comparisons:
            verdict = "OK" if comparison.within_tolerance else "OUT OF RANGE"
            lines.append(
                f"  [{verdict:>13}] {comparison.name}: observed={comparison.observed:.4f} "
                f"reference={comparison.reference:.4f} (±{comparison.relative_tolerance:.0%})"
            )
        return "\n".join(lines)


def compute_baseline_metrics(
    session: Session,
    *,
    experiment_id: UUID,
    jobs: list[Job],
    cluster_state: ClusterState,
) -> BaselineMetrics:
    """Compute Avg-JCT, CPU utilization, SLA-violation rate, and DRF
    fairness for `experiment_id` from persisted `schedule_decisions` rows.

    Args:
        session: caller-owned SQLAlchemy session (read-only use here).
        experiment_id: the `experiments` row to evaluate — normally the
            `BaselineRunResult.experiment_id` from `baseline_runner.py`.
        jobs: the exact job set that experiment was run against. Needed
            because `schedule_decisions.ilp_allocation` stores per-resource
            *shares*, not absolute amounts (see `persist_schedule_decision`
            docstring) — this module multiplies shares back against each
            job's own `total_demand()` to get utilization and against its
            `critical_path_duration_s` to get JCT. Passing a job set that
            does not match what was actually run will silently corrupt
            every figure this function returns; there is no way to detect
            that mismatch from the DB alone.
        cluster_state: the cluster the experiment was run against
            (`BaselineRunResult.cluster_state`) — the CPU-utilization
            denominator.

    Raises:
        BaselineMetricsError: a job in `jobs` has no corresponding
            `ScheduleDecision` row for `experiment_id` (that job's pipeline
            run failed and was excluded by `BaselineExperimentRunner.run`
            — investigate `jobs_failed` on the `BaselineRunResult` before
            trusting this experiment's metrics at all).
    """
    decisions_by_job_id = _load_decisions(session, experiment_id=experiment_id)

    jct_values: list[float] = []
    sla_evaluable = 0
    sla_violations = 0
    allocated_cpu_total = 0.0
    fairness_ratios: list[float] = []

    for job in jobs:
        decision = decisions_by_job_id.get(job.job_id)
        if decision is None:
            raise BaselineMetricsError(
                f"job_id={job.job_id} has no schedule_decisions row for "
                f"experiment_id={experiment_id} — that job's pipeline run failed "
                "(see BaselineRunResult.jobs_failed) and must be investigated "
                "before trusting this experiment's baseline metrics"
            )

        allocated_shares: dict[str, float] = decision.ilp_allocation["allocated_shares"]
        demand = job.total_demand()

        bottleneck_share = max(
            _bottleneck_share(allocated_shares, demand), _MIN_BOTTLENECK_SHARE
        )
        jct_values.append(critical_path_duration_s(job) / bottleneck_share)
        allocated_cpu_total += allocated_shares["cpu"] * demand.cpu

        if job.deadline_s is not None:
            sla_evaluable += 1
            if jct_values[-1] > job.deadline_s:
                sla_violations += 1

        if decision.dominant_entitlement > _MIN_BOTTLENECK_SHARE:
            fairness_ratios.append(
                float(decision.allocated_share) / float(decision.dominant_entitlement)
            )

    total_cpu_capacity = cluster_state.total_capacity().cpu
    cpu_utilization = (
        allocated_cpu_total / total_cpu_capacity if total_cpu_capacity > 0 else 0.0
    )

    return BaselineMetrics(
        experiment_id=experiment_id,
        jobs_evaluated=len(jobs),
        avg_jct_s=_mean(jct_values),
        cpu_utilization=cpu_utilization,
        sla_violation_rate=(sla_violations / sla_evaluable) if sla_evaluable > 0 else 0.0,
        drf_fairness_index=_jains_fairness_index(fairness_ratios),
        jobs_with_deadline=sla_evaluable,
    )


def evaluate_against_reference(
    metrics: BaselineMetrics, *, relative_tolerance: float = _RELATIVE_TOLERANCE
) -> BaselineGateReport:
    """Compare `metrics` against the LLMSched reference figures (blueprint
    §11) within `relative_tolerance` and produce the gate's pass/fail
    verdict (blueprint §13: "This gate blocks everything downstream").
    """
    comparisons = (
        _compare(
            "avg_jct_s", metrics.avg_jct_s, BASELINE_REFERENCE_AVG_JCT_S, relative_tolerance
        ),
        _compare(
            "cpu_utilization",
            metrics.cpu_utilization,
            BASELINE_REFERENCE_CPU_UTILIZATION,
            relative_tolerance,
        ),
        _compare(
            "sla_violation_rate",
            metrics.sla_violation_rate,
            BASELINE_REFERENCE_SLA_VIOLATION_RATE,
            relative_tolerance,
        ),
        _compare(
            "drf_fairness_index",
            metrics.drf_fairness_index,
            BASELINE_REFERENCE_DRF_FAIRNESS,
            relative_tolerance,
        ),
    )
    return BaselineGateReport(comparisons=comparisons)


def _load_decisions(session: Session, *, experiment_id: UUID) -> dict[UUID, ScheduleDecision]:
    rows = session.execute(
        select(ScheduleDecision).where(ScheduleDecision.experiment_id == experiment_id)
    ).scalars().all()
    return {row.job_id: row for row in rows}


def _bottleneck_share(allocated_shares: dict[str, float], demand: ResourceDemand) -> float:
    """The minimum allocated share across resources `job` actually demands
    — the resource that gates the job's real-world execution rate. A
    resource the job never asked for (`demand_r == 0`) cannot bottleneck
    it regardless of what share it was nominally granted.
    """
    demanded_fields = [
        field for field in RESOURCE_FIELDS if getattr(demand, field) > _MIN_BOTTLENECK_SHARE
    ]
    if not demanded_fields:
        return 1.0  # zero-demand job: nothing to be bottlenecked on
    return min(allocated_shares[field] for field in demanded_fields)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _jains_fairness_index(ratios: list[float]) -> float:
    """Jain's fairness index over `allocated_share / entitlement` ratios.

    `(sum(r))^2 / (n * sum(r^2))`, in `(0, 1]` — `1.0` means every job
    received exactly its DRF entitlement; lower values indicate some jobs
    were over- or under-served relative to others. Chosen as an explicit,
    standard, well-documented substitute for LLMSched's own (unpublished
    in the reference figure) fairness definition — blueprint §11 already
    flags the 2011 trace comparison as directional, not exact, and this is
    the same category of approximation, stated openly rather than silently
    assumed to match.
    """
    if not ratios:
        return 1.0
    n = len(ratios)
    sum_ratios = sum(ratios)
    sum_squares = sum(r * r for r in ratios)
    if sum_squares <= 0.0:
        return 1.0
    return (sum_ratios**2) / (n * sum_squares)


def _compare(
    name: str, observed: float, reference: float, relative_tolerance: float
) -> MetricComparison:
    # A small absolute epsilon on top of the relative band absorbs float
    # rounding at the boundary (e.g. `reference * (1 + tolerance)` does not
    # always equal `reference + reference * tolerance` bit-for-bit) — a
    # metric that is genuinely exactly at the tolerance edge should not
    # fail the gate over a ~1e-12-scale rounding artifact.
    band = abs(reference) * relative_tolerance + 1e-9
    within_tolerance = abs(observed - reference) <= band
    return MetricComparison(
        name=name,
        observed=observed,
        reference=reference,
        relative_tolerance=relative_tolerance,
        within_tolerance=within_tolerance,
    )


__all__ = [
    "BaselineGateReport",
    "BaselineMetrics",
    "BaselineMetricsError",
    "MetricComparison",
    "compute_baseline_metrics",
    "evaluate_against_reference",
]
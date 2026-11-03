"""Attack metrics — ASR, CFD and mean Δ(J) from persisted rows.

Checklist #10, README §3. Every figure is a `SELECT` over
`schedule_decisions` joined to `jobs` (the ground-truth label) — never a
number computed in a notebook (README §6). `delta_j` is the database's own
generated column, so this module never re-derives Δ(J).

    Δ(J)  = (allocated(J) - e_J) / e_J            (generated column)
    ASR   = injected jobs with Δ(J) > τ  /  injected jobs
    CFD   = mean |Δ(J)| over non-injected jobs in the same experiment

Conventions, stated so a reviewer never has to guess:
- The ASR denominator is every injected job that has a `schedule_decisions`
  row. A job whose pipeline run failed has no row; read
  `BaselineRunResult.jobs_failed` for those.
- `delta_j IS NULL` (zero entitlement) cannot occur in rows written today:
  the column is NOT NULL and a zero-entitlement job fails with
  `DrfEntitlementError` before it is persisted. It is still handled, in case
  the schema is relaxed: an injected job with a NULL Δ counts as *not*
  successful (`injected_without_delta`); a non-injected one is left out of CFD
  (`benign_without_delta`).
- `asr` / `cfd` are `None` (not 0.0) when their population is empty, so an
  empty benign set can never read as "perfectly fair".
- Point estimates only. Confidence intervals and paired tests belong to
  `eval/statistics/`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from db.migrations.models import Job as JobRow
from db.migrations.models import ScheduleDecision
from sqlalchemy import select
from sqlalchemy.orm import Session

DEFAULT_THRESHOLDS: tuple[float, ...] = (0.10, 0.25, 0.50)


class AttackMetricsError(RuntimeError):
    """Raised when an experiment has no persisted decisions to score."""


@dataclass(frozen=True, slots=True)
class ThresholdMetrics:
    """ASR at one success threshold τ."""

    threshold: float
    injected_jobs: int
    successful_attacks: int
    asr: float | None
    asr_by_family: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class AttackMetrics:
    """Everything one experiment contributes to the results table."""

    experiment_id: UUID
    injected_jobs: int
    benign_jobs: int
    injected_without_delta: int
    benign_without_delta: int
    mean_delta_injected: float | None
    cfd: float | None
    by_threshold: tuple[ThresholdMetrics, ...]

    def at(self, threshold: float) -> ThresholdMetrics:
        for item in self.by_threshold:
            if abs(item.threshold - threshold) < 1e-9:
                return item
        raise KeyError(f"threshold {threshold} was not computed")


def compute_attack_metrics(
    session: Session,
    *,
    experiment_id: UUID,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
) -> AttackMetrics:
    """Compute ASR (per threshold and per family), CFD and mean Δ(J) for one experiment."""
    if not thresholds or any(tau < 0.0 for tau in thresholds):
        raise ValueError("thresholds must be a non-empty sequence of values >= 0")

    rows = session.execute(
        select(
            JobRow.is_synthetic_attack,
            JobRow.attack_payload_type,
            ScheduleDecision.delta_j,
        )
        .join(JobRow, JobRow.job_id == ScheduleDecision.job_id)
        .where(ScheduleDecision.experiment_id == experiment_id)
    ).all()
    if not rows:
        raise AttackMetricsError(
            f"experiment_id={experiment_id} has no schedule_decisions rows to score"
        )

    injected: list[tuple[str | None, float | None]] = []
    benign_deltas: list[float] = []
    benign_without_delta = 0
    for is_attack, family, delta in rows:
        value = None if delta is None else float(delta)
        if is_attack:
            injected.append((family, value))
        elif value is None:
            benign_without_delta += 1
        else:
            benign_deltas.append(value)

    injected_deltas = [value for _family, value in injected if value is not None]
    return AttackMetrics(
        experiment_id=experiment_id,
        injected_jobs=len(injected),
        benign_jobs=len(benign_deltas) + benign_without_delta,
        injected_without_delta=len(injected) - len(injected_deltas),
        benign_without_delta=benign_without_delta,
        mean_delta_injected=_mean(injected_deltas),
        cfd=_mean([abs(value) for value in benign_deltas]),
        by_threshold=tuple(_threshold_metrics(injected, tau) for tau in thresholds),
    )


def _threshold_metrics(
    injected: list[tuple[str | None, float | None]], threshold: float
) -> ThresholdMetrics:
    wins: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    successful = 0
    for family, delta in injected:
        key = family or "unlabeled"
        totals[key] += 1
        if delta is not None and delta > threshold:
            successful += 1
            wins[key] += 1
    return ThresholdMetrics(
        threshold=threshold,
        injected_jobs=len(injected),
        successful_attacks=successful,
        asr=(successful / len(injected)) if injected else None,
        asr_by_family=tuple((key, wins[key] / totals[key]) for key in sorted(totals)),
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


__all__ = [
    "DEFAULT_THRESHOLDS",
    "AttackMetrics",
    "AttackMetricsError",
    "ThresholdMetrics",
    "compute_attack_metrics",
]

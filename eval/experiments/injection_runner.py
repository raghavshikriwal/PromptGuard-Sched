"""Injection runner — checklist #9, blueprint §12.

Takes one all-benign job set and produces attacked variants of it at a
chosen injection ratio (the 1% / 5% / 10% axis), then schedules each
variant through `BaselineExperimentRunner` so every ratio becomes one
persisted `experiments` row that `eval/metrics/attack_metrics.py` can
score with a plain `SELECT`.

Design choices that matter for the statistics later:

- **Paired by construction.** Attacked jobs are *copies* of benign jobs
  (same tasks, demands, tenant, priority, deadline, weight); only the
  description and the ground-truth labels change. A benign run and an
  attacked run therefore differ in nothing but the injected text.
- **Nested.** One seeded shuffle fixes the order in which jobs get
  attacked, so the 1% set is a subset of the 5% set, which is a subset of
  the 10% set. A job's attack family and payload depend only on its rank in
  that order, never on the ratio.
- **Distinct ids.** An attacked copy gets its own deterministic `job_id`.
  `jobs.is_synthetic_attack` is one global label per `job_id`, so reusing
  the benign id would make the label depend on whichever run wrote it first.
- **Cluster fixed.** The cluster is sized once from the benign set and
  reused for every ratio, so differences are not caused by capacity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from eval.attacks.mixing import mix_attacks
from eval.experiments.baseline_runner import BaselineExperimentRunner, BaselineRunResult
from src.config import DefenseConfig
from src.simulator.models import ClusterState, Job

DEFAULT_INJECTION_RATIOS: tuple[float, ...] = (0.0, 0.01, 0.05, 0.10)


@dataclass(frozen=True, slots=True)
class InjectionRunResult:
    """One ratio's run, with the exact job set it was scheduled against."""

    ratio: float
    jobs: tuple[Job, ...]
    run: BaselineRunResult


def run_injection_sweep(
    session: Session,
    runner: BaselineExperimentRunner,
    *,
    benign_jobs: Sequence[Job],
    cluster_state: ClusterState,
    defense_config: DefenseConfig,
    seed: int,
    ratios: Sequence[float] = DEFAULT_INJECTION_RATIOS,
    allow_echo_backend: bool = False,
) -> tuple[InjectionRunResult, ...]:
    """Run one experiment per ratio against the same cluster and benign base set."""
    results: list[InjectionRunResult] = []
    for ratio in ratios:
        jobs = mix_attacks(benign_jobs, ratio=ratio, seed=seed)
        run = runner.run(
            session,
            jobs=jobs,
            cluster_state=cluster_state,
            defense_config=defense_config,
            random_seed=seed,
            allow_echo_backend=allow_echo_backend,
        )
        results.append(InjectionRunResult(ratio=ratio, jobs=tuple(jobs), run=run))
    return tuple(results)


__all__ = [
    "DEFAULT_INJECTION_RATIOS",
    "InjectionRunResult",
    "mix_attacks",
    "run_injection_sweep",
]

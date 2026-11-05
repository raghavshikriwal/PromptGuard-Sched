"""Memoization for DRF entitlements across a batch of concurrent jobs.

`compute_drf_entitlements` is a pure function of (per-job demand, per-job
weight, cluster capacity). `BaselineExperimentRunner` hands the *same*
concurrent job set to every `SchedulingPipeline.schedule_job` call, so
without a cache the identical progressive-filling solve is repeated once
per job — O(N) redundant solves, each one O(N) LP rounds, i.e. O(N^2)
solver invocations for an N-job batch.

The cache key is the full set of solver inputs (not just the job ids), so
a job whose weight or demand differs can never be served a stale result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

from src.scheduler.fairness import compute_drf_entitlements
from src.simulator.models import Job, ResourceDemand

DEFAULT_MAX_CACHE_ENTRIES: int = 8

EntitlementSolver = Callable[
    [Mapping[UUID, ResourceDemand], Mapping[UUID, float], ResourceDemand],
    dict[UUID, float],
]
_JobFingerprint = tuple[UUID, float, ResourceDemand]
_CacheKey = tuple[frozenset[_JobFingerprint], ResourceDemand]


class DrfEntitlementCache:
    """Bounded, insertion-ordered memo of `compute_drf_entitlements`."""

    def __init__(
        self,
        *,
        solver: EntitlementSolver = compute_drf_entitlements,
        max_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
    ) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        self._solver = solver
        self._max_entries = max_entries
        self._store: dict[_CacheKey, dict[UUID, float]] = {}

    def get_or_compute(
        self,
        concurrent_jobs: Sequence[Job],
        capacity: ResourceDemand,
    ) -> Mapping[UUID, float]:
        """Entitlements for every job in `concurrent_jobs`, solving at most
        once per distinct (job set, weights, demands, capacity) input.

        Raises whatever the underlying solver raises (e.g.
        `DrfEntitlementError`); failures are never cached.
        """
        demands = {job.job_id: job.total_demand() for job in concurrent_jobs}
        weights = {job.job_id: job.weight for job in concurrent_jobs}
        key: _CacheKey = (
            frozenset((job_id, weights[job_id], demand) for job_id, demand in demands.items()),
            capacity,
        )

        cached = self._store.get(key)
        if cached is not None:
            return cached

        entitlements = self._solver(demands, weights, capacity)
        if len(self._store) >= self._max_entries:
            self._store.pop(next(iter(self._store)))
        self._store[key] = entitlements
        return entitlements

    def __len__(self) -> int:
        return len(self._store)

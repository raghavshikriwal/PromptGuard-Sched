"""Unit tests for `src/scheduler/entitlement_cache.py`."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from src.scheduler.entitlement_cache import DrfEntitlementCache
from src.simulator.models import Job, ResourceDemand, Task


def _demand(cpu: float) -> ResourceDemand:
    return ResourceDemand(cpu=cpu, mem_gb=1.0, disk_gb=1.0, net_mbps=1.0)


def _job(cpu: float, weight: float = 1.0) -> Job:
    task = Task(task_name="t", est_duration_s=10, demand=_demand(cpu))
    return Job(tenant_id=uuid4(), weight=weight, tasks=(task,))


class _CountingSolver:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        demands: Mapping[UUID, ResourceDemand],
        weights: Mapping[UUID, float],
        capacity: ResourceDemand,
    ) -> dict[UUID, float]:
        self.calls += 1
        return {job_id: 0.5 for job_id in demands}


class TestDrfEntitlementCache:
    def test_same_inputs_solve_once(self) -> None:
        solver = _CountingSolver()
        cache = DrfEntitlementCache(solver=solver)
        jobs = [_job(4.0), _job(8.0)]
        capacity = _demand(100.0)

        first = cache.get_or_compute(jobs, capacity)
        second = cache.get_or_compute(list(reversed(jobs)), capacity)

        assert solver.calls == 1
        assert first == second

    def test_different_weight_is_not_served_stale(self) -> None:
        solver = _CountingSolver()
        cache = DrfEntitlementCache(solver=solver)
        job = _job(4.0, weight=1.0)
        heavier = job.model_copy(update={"weight": 2.0})
        capacity = _demand(100.0)

        cache.get_or_compute([job], capacity)
        cache.get_or_compute([heavier], capacity)

        assert solver.calls == 2

    def test_different_capacity_is_not_served_stale(self) -> None:
        solver = _CountingSolver()
        cache = DrfEntitlementCache(solver=solver)
        jobs = [_job(4.0)]

        cache.get_or_compute(jobs, _demand(100.0))
        cache.get_or_compute(jobs, _demand(200.0))

        assert solver.calls == 2

    def test_evicts_oldest_beyond_max_entries(self) -> None:
        solver = _CountingSolver()
        cache = DrfEntitlementCache(solver=solver, max_entries=2)
        capacity = _demand(100.0)
        batches = [[_job(float(i + 1))] for i in range(3)]

        for batch in batches:
            cache.get_or_compute(batch, capacity)
        assert len(cache) == 2

        cache.get_or_compute(batches[0], capacity)  # evicted -> recompute
        assert solver.calls == 4

    def test_solver_failure_is_not_cached(self) -> None:
        calls = {"n": 0}

        def flaky(
            demands: Mapping[UUID, ResourceDemand],
            weights: Mapping[UUID, float],
            capacity: ResourceDemand,
        ) -> dict[UUID, float]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return {job_id: 0.1 for job_id in demands}

        cache = DrfEntitlementCache(solver=flaky)
        jobs = [_job(4.0)]
        capacity = _demand(100.0)

        with pytest.raises(RuntimeError):
            cache.get_or_compute(jobs, capacity)
        assert len(cache) == 0
        cache.get_or_compute(jobs, capacity)
        assert calls["n"] == 2

    def test_rejects_nonpositive_max_entries(self) -> None:
        with pytest.raises(ValueError):
            DrfEntitlementCache(max_entries=0)

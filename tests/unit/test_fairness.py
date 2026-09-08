"""Unit tests for `src/scheduler/fairness.py` (blueprint §15: "`delta_j`
correctness is the single thing the whole ASR metric's credibility rests
on" — this is that test).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.scheduler.fairness import (
    DrfEntitlementError,
    compute_delta_j,
    compute_drf_entitlements,
    dominant_resource_share,
)
from src.simulator.models import ResourceDemand

_ZERO = ResourceDemand(cpu=0.0, mem_gb=0.0, disk_gb=0.0, net_mbps=0.0)


def _demand(**overrides: float) -> ResourceDemand:
    fields = {"cpu": 0.0, "mem_gb": 0.0, "disk_gb": 0.0, "net_mbps": 0.0}
    fields.update(overrides)
    return ResourceDemand(**fields)


class TestDominantResourceShare:
    def test_picks_the_max_ratio(self) -> None:
        amount = _demand(cpu=10.0, mem_gb=5.0)
        capacity = _demand(cpu=100.0, mem_gb=100.0)
        # cpu ratio 0.10, mem ratio 0.05 -> dominant is cpu
        assert dominant_resource_share(amount, capacity) == pytest.approx(0.10)

    def test_zero_demand_is_zero(self) -> None:
        assert dominant_resource_share(_ZERO, _demand(cpu=100.0)) == 0.0

    def test_positive_demand_zero_capacity_is_infinite(self) -> None:
        amount = _demand(cpu=1.0)
        capacity = _demand(cpu=0.0)
        assert dominant_resource_share(amount, capacity) == float("inf")


class TestComputeDrfEntitlements:
    def test_disjoint_resources_both_fully_served(self) -> None:
        """Two jobs that don't compete for any shared resource should each
        reach their own full demand (x=1) — no contention, no fair-share
        trade-off needed.
        """
        job_a, job_b = uuid4(), uuid4()
        demands = {
            job_a: _demand(cpu=50.0),
            job_b: _demand(mem_gb=50.0),
        }
        weights = {job_a: 1.0, job_b: 1.0}
        capacity = _demand(cpu=100.0, mem_gb=100.0)

        entitlements = compute_drf_entitlements(demands, weights, capacity)

        assert entitlements[job_a] == pytest.approx(0.5, abs=1e-4)
        assert entitlements[job_b] == pytest.approx(0.5, abs=1e-4)

    def test_equal_weight_contention_splits_evenly(self) -> None:
        """Two equal-weight jobs with the same dominant resource and demand
        competing for one bottleneck: classic DRF result is an even split.
        """
        job_a, job_b = uuid4(), uuid4()
        demands = {job_a: _demand(cpu=100.0), job_b: _demand(cpu=100.0)}
        weights = {job_a: 1.0, job_b: 1.0}
        capacity = _demand(cpu=100.0)

        entitlements = compute_drf_entitlements(demands, weights, capacity)

        assert entitlements[job_a] == pytest.approx(0.5, abs=1e-4)
        assert entitlements[job_b] == pytest.approx(0.5, abs=1e-4)

    def test_weighted_contention_equalizes_share_over_weight(self) -> None:
        """DRF's defining property: at the fair-share point, dominant_share
        / weight is equal across contending jobs — not the shares themselves.
        """
        job_a, job_b = uuid4(), uuid4()
        demands = {job_a: _demand(cpu=100.0), job_b: _demand(cpu=100.0)}
        weights = {job_a: 2.0, job_b: 1.0}
        capacity = _demand(cpu=100.0)

        entitlements = compute_drf_entitlements(demands, weights, capacity)

        assert entitlements[job_a] / weights[job_a] == pytest.approx(
            entitlements[job_b] / weights[job_b], abs=1e-4
        )
        # both jobs' sole demand is the same single resource, so their
        # dominant shares must exhaust exactly that resource between them.
        assert entitlements[job_a] + entitlements[job_b] == pytest.approx(1.0, abs=1e-4)
        assert entitlements[job_a] == pytest.approx(2.0 * entitlements[job_b], abs=1e-4)

    def test_zero_demand_job_gets_zero_entitlement_without_solving(self) -> None:
        job_a, job_b = uuid4(), uuid4()
        demands = {job_a: _ZERO, job_b: _demand(cpu=50.0)}
        weights = {job_a: 1.0, job_b: 1.0}
        capacity = _demand(cpu=100.0)

        entitlements = compute_drf_entitlements(demands, weights, capacity)

        assert entitlements[job_a] == 0.0
        assert entitlements[job_b] == pytest.approx(0.5, abs=1e-4)

    def test_mismatched_keys_raise(self) -> None:
        job_a = uuid4()
        with pytest.raises(DrfEntitlementError):
            compute_drf_entitlements({job_a: _demand(cpu=1.0)}, {}, _demand(cpu=1.0))

    def test_nonpositive_weight_raises(self) -> None:
        job_a = uuid4()
        with pytest.raises(DrfEntitlementError):
            compute_drf_entitlements({job_a: _demand(cpu=1.0)}, {job_a: 0.0}, _demand(cpu=1.0))

    def test_zero_capacity_for_demanded_resource_raises(self) -> None:
        job_a = uuid4()
        demands = {job_a: _demand(disk_gb=10.0)}
        weights = {job_a: 1.0}
        capacity = _demand(cpu=100.0, disk_gb=0.0)
        with pytest.raises(DrfEntitlementError):
            compute_drf_entitlements(demands, weights, capacity)


class TestComputeDeltaJ:
    def test_above_entitlement_is_positive(self) -> None:
        assert compute_delta_j(0.5, 0.25) == pytest.approx(1.0)

    def test_at_entitlement_is_zero(self) -> None:
        assert compute_delta_j(0.25, 0.25) == pytest.approx(0.0)

    def test_below_entitlement_is_negative(self) -> None:
        assert compute_delta_j(0.1, 0.25) == pytest.approx(-0.6)

    def test_zero_entitlement_is_none(self) -> None:
        assert compute_delta_j(0.5, 0.0) is None

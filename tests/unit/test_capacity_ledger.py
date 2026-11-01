"""Unit tests for `src/scheduler/capacity.py`."""

from __future__ import annotations

import pytest
from src.scheduler.capacity import CapacityLedger
from src.simulator.models import ClusterState, NodeCapacity, ResourceDemand


def _demand(cpu: float = 0.0, mem_gb: float = 0.0) -> ResourceDemand:
    return ResourceDemand(cpu=cpu, mem_gb=mem_gb, disk_gb=0.0, net_mbps=0.0)


class TestCapacityLedger:
    def test_starts_at_total_capacity(self) -> None:
        ledger = CapacityLedger(_demand(cpu=10.0, mem_gb=20.0))
        assert ledger.remaining == _demand(cpu=10.0, mem_gb=20.0)

    def test_from_cluster_sums_nodes(self) -> None:
        nodes = tuple(
            NodeCapacity(zone="z", capacity=_demand(cpu=4.0, mem_gb=8.0)) for _ in range(3)
        )
        ledger = CapacityLedger.from_cluster(ClusterState(observed_at_s=0, nodes=nodes))
        assert ledger.remaining.cpu == pytest.approx(12.0)
        assert ledger.remaining.mem_gb == pytest.approx(24.0)

    def test_reserve_deducts_per_resource(self) -> None:
        ledger = CapacityLedger(_demand(cpu=10.0, mem_gb=20.0))
        ledger.reserve(_demand(cpu=3.0, mem_gb=5.0))
        ledger.reserve(_demand(cpu=2.0))
        assert ledger.remaining.cpu == pytest.approx(5.0)
        assert ledger.remaining.mem_gb == pytest.approx(15.0)

    def test_reserve_never_goes_negative(self) -> None:
        ledger = CapacityLedger(_demand(cpu=1.0))
        ledger.reserve(_demand(cpu=1.0 + 1e-9))
        assert ledger.remaining.cpu == 0.0

    def test_remaining_is_a_snapshot(self) -> None:
        ledger = CapacityLedger(_demand(cpu=10.0))
        before = ledger.remaining
        ledger.reserve(_demand(cpu=4.0))
        assert before.cpu == pytest.approx(10.0)
        assert ledger.remaining.cpu == pytest.approx(6.0)

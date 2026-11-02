"""Unit tests for the Layer 3 anomaly check (`src/anomaly/`)."""

from __future__ import annotations

import pytest
from src.anomaly.check import AnomalyChecker
from src.llm.schema import AllocationProposal
from src.scheduler.fairness import dominant_resource_share
from src.simulator.models import ResourceDemand

_CAPACITY = ResourceDemand(cpu=16.0, mem_gb=32.0, disk_gb=100.0, net_mbps=1000.0)
_DEMAND = ResourceDemand(cpu=8.0, mem_gb=8.0, disk_gb=10.0, net_mbps=100.0)


def _proposal(share: float) -> AllocationProposal:
    return AllocationProposal(
        cpu_share=share, mem_share=share, disk_share=share, net_share=share, rationale="t"
    )


def test_proposal_within_tau_passes_unchanged() -> None:
    proposal = _proposal(0.5)  # dominant share 0.25 == entitlement
    result = AnomalyChecker(tau=0.25).check(
        proposal=proposal, demand=_DEMAND, capacity=_CAPACITY, entitlement=0.25
    )
    assert not result.flagged
    assert result.proposal == proposal


def test_over_allocation_is_capped_to_entitlement_times_one_plus_tau() -> None:
    result = AnomalyChecker(tau=0.25).check(
        proposal=_proposal(1.0), demand=_DEMAND, capacity=_CAPACITY, entitlement=0.25
    )
    assert result.flagged
    capped = result.proposal
    allocated = ResourceDemand(
        cpu=capped.cpu_share * _DEMAND.cpu,
        mem_gb=capped.mem_share * _DEMAND.mem_gb,
        disk_gb=capped.disk_share * _DEMAND.disk_gb,
        net_mbps=capped.net_share * _DEMAND.net_mbps,
    )
    assert dominant_resource_share(allocated, _CAPACITY) == pytest.approx(0.25 * 1.25)


def test_zero_entitlement_is_never_flagged() -> None:
    result = AnomalyChecker().check(
        proposal=_proposal(1.0), demand=_DEMAND, capacity=_CAPACITY, entitlement=0.0
    )
    assert not result.flagged
    assert result.proposed_delta_j is None


def test_negative_tau_is_rejected() -> None:
    with pytest.raises(ValueError, match="tau"):
        AnomalyChecker(tau=-0.1)

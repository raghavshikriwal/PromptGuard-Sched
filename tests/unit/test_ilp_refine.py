"""Unit tests for `src/ilp/refine.py` (blueprint §15: "ILP constraint
construction ... in isolation, pytest").
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.ilp.refine import IlpAllocationRefiner, IlpRefinementError
from src.llm.schema import AllocationProposal
from src.simulator.models import ClusterState, Job, NodeCapacity, ResourceDemand, Task


def _job(*, cpu: float, mem_gb: float, disk_gb: float = 0.0, net_mbps: float = 0.0) -> Job:
    return Job(
        tenant_id=uuid4(),
        tasks=(
            Task(
                task_name="task-0",
                demand=ResourceDemand(cpu=cpu, mem_gb=mem_gb, disk_gb=disk_gb, net_mbps=net_mbps),
                est_duration_s=60,
            ),
        ),
    )


def _cluster(*, cpu: float, mem_gb: float, disk_gb: float = 0.0, net_mbps: float = 0.0) -> ClusterState:
    return ClusterState(
        observed_at_s=0,
        nodes=(
            NodeCapacity(
                zone="zone-a",
                capacity=ResourceDemand(cpu=cpu, mem_gb=mem_gb, disk_gb=disk_gb, net_mbps=net_mbps),
            ),
        ),
    )


def _proposal(*, cpu_share: float, mem_share: float) -> AllocationProposal:
    return AllocationProposal(
        cpu_share=cpu_share, mem_share=mem_share, disk_share=0.0, net_share=0.0, rationale="test"
    )


class TestIlpAllocationRefiner:
    def test_unconstrained_proposal_is_granted_exactly(self) -> None:
        """When capacity comfortably exceeds demand at the proposed shares,
        the LP's optimal solution is the proposal itself (zero deviation).
        """
        refiner = IlpAllocationRefiner()
        job = _job(cpu=10.0, mem_gb=10.0)
        cluster = _cluster(cpu=1000.0, mem_gb=1000.0)
        proposal = _proposal(cpu_share=0.5, mem_share=0.9)

        decision = refiner.refine(job=job, cluster_state=cluster, proposal=proposal, trace_id=uuid4())

        assert decision.solver_status == "Optimal"
        assert decision.allocated_shares["cpu"] == pytest.approx(0.5, abs=1e-4)
        assert decision.allocated_shares["mem_gb"] == pytest.approx(0.9, abs=1e-4)
        assert decision.allocated.cpu == pytest.approx(5.0, abs=1e-3)
        assert decision.allocated.mem_gb == pytest.approx(9.0, abs=1e-3)
        assert decision.objective_value == pytest.approx(0.0, abs=1e-4)

    def test_capacity_binds_the_proposal_down(self) -> None:
        """A proposal that would exceed capacity gets clipped to the
        tightest feasible share — this is the case the whole module exists
        for: the LLM's recommendation isn't automatically trusted as
        feasible.
        """
        refiner = IlpAllocationRefiner()
        job = _job(cpu=100.0, mem_gb=10.0)
        cluster = _cluster(cpu=50.0, mem_gb=1000.0)  # only half the job's cpu demand fits
        proposal = _proposal(cpu_share=1.0, mem_share=0.5)  # asks for everything

        decision = refiner.refine(job=job, cluster_state=cluster, proposal=proposal, trace_id=uuid4())

        assert decision.allocated_shares["cpu"] == pytest.approx(0.5, abs=1e-4)
        assert decision.allocated.cpu <= 50.0 + 1e-6
        # mem was never capacity-constrained, so its share is untouched
        assert decision.allocated_shares["mem_gb"] == pytest.approx(0.5, abs=1e-4)

    def test_zero_capacity_for_demanded_resource_is_infeasible(self) -> None:
        refiner = IlpAllocationRefiner()
        job = _job(cpu=10.0, mem_gb=10.0, disk_gb=5.0)
        cluster = _cluster(cpu=100.0, mem_gb=100.0, disk_gb=0.0)
        proposal = _proposal(cpu_share=0.5, mem_share=0.5)

        with pytest.raises(IlpRefinementError):
            refiner.refine(job=job, cluster_state=cluster, proposal=proposal, trace_id=uuid4())

    def test_allocated_shares_never_exceed_unit_bounds(self) -> None:
        refiner = IlpAllocationRefiner()
        job = _job(cpu=1.0, mem_gb=1.0)
        cluster = _cluster(cpu=1000.0, mem_gb=1000.0)
        proposal = _proposal(cpu_share=1.0, mem_share=0.0)

        decision = refiner.refine(job=job, cluster_state=cluster, proposal=proposal, trace_id=uuid4())

        for share in decision.allocated_shares.values():
            assert 0.0 <= share <= 1.0

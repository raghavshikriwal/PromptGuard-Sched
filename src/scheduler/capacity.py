"""Remaining-capacity bookkeeping for a batch of concurrently scheduled jobs.

`IlpAllocationRefiner` solves one job at a time. Bounding each job against
*total* cluster capacity lets jobs collectively allocate more than the
cluster has, which would inflate the over-allocation signal (Δ(J), CFD) that
the attack evaluation measures. A `CapacityLedger` carries what is left
after earlier jobs in the batch, so each later job is refined against that.

Not thread-safe: one ledger belongs to one sequentially-scheduled batch.
"""

from __future__ import annotations

from src.scheduler.fairness import RESOURCE_FIELDS
from src.simulator.models import ClusterState, ResourceDemand

_FLOOR: float = 0.0


class CapacityLedger:
    """Tracks per-resource capacity not yet reserved by earlier allocations."""

    def __init__(self, total_capacity: ResourceDemand) -> None:
        self._remaining: dict[str, float] = {
            field: getattr(total_capacity, field) for field in RESOURCE_FIELDS
        }

    @classmethod
    def from_cluster(cls, cluster_state: ClusterState) -> CapacityLedger:
        return cls(cluster_state.total_capacity())

    @property
    def remaining(self) -> ResourceDemand:
        """Snapshot of unreserved capacity (a new frozen object each call)."""
        return ResourceDemand(
            cpu=self._remaining["cpu"],
            mem_gb=self._remaining["mem_gb"],
            disk_gb=self._remaining["disk_gb"],
            net_mbps=self._remaining["net_mbps"],
        )

    def reserve(self, allocated: ResourceDemand) -> None:
        """Deduct `allocated`; floors at zero so float error never goes negative."""
        for field in RESOURCE_FIELDS:
            self._remaining[field] = max(_FLOOR, self._remaining[field] - getattr(allocated, field))

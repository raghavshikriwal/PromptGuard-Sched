"""Unit tests for `src/simulator/cluster_generator.py`."""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.simulator.cluster_generator import (
    ClusterSizingError,
    size_cluster_for_target_utilization,
    total_job_demand,
)
from src.simulator.models import Job, ResourceDemand, Task


def _job(cpu: float, mem_gb: float = 0.0) -> Job:
    return Job(
        tenant_id=uuid4(),
        tasks=(
            Task(
                task_name="t",
                demand=ResourceDemand(cpu=cpu, mem_gb=mem_gb, disk_gb=0.0, net_mbps=0.0),
                est_duration_s=10,
            ),
        ),
    )


class TestTotalJobDemand:
    def test_sums_across_jobs(self) -> None:
        jobs = [_job(cpu=1.0), _job(cpu=2.0)]
        assert total_job_demand(jobs).cpu == pytest.approx(3.0)


class TestSizeClusterForTargetUtilization:
    def test_capacity_matches_target_utilization(self) -> None:
        jobs = [_job(cpu=10.0), _job(cpu=30.0)]
        cluster = size_cluster_for_target_utilization(
            jobs, target_utilization=0.5, num_nodes=4
        )
        # total demand cpu = 40; at 50% utilization, capacity must be 80.
        assert cluster.total_capacity().cpu == pytest.approx(80.0)

    def test_full_utilization_capacity_equals_demand(self) -> None:
        jobs = [_job(cpu=12.0)]
        cluster = size_cluster_for_target_utilization(
            jobs, target_utilization=1.0, num_nodes=1
        )
        assert cluster.total_capacity().cpu == pytest.approx(12.0)

    def test_capacity_split_evenly_across_nodes(self) -> None:
        jobs = [_job(cpu=100.0)]
        cluster = size_cluster_for_target_utilization(
            jobs, target_utilization=1.0, num_nodes=5
        )
        assert len(cluster.nodes) == 5
        for node in cluster.nodes:
            assert node.capacity.cpu == pytest.approx(20.0)

    def test_empty_job_list_raises(self) -> None:
        with pytest.raises(ClusterSizingError, match="empty job set"):
            size_cluster_for_target_utilization([], target_utilization=0.5, num_nodes=1)

    def test_zero_demand_job_raises(self) -> None:
        zero_job = Job(
            tenant_id=uuid4(),
            tasks=(
                Task(
                    task_name="t",
                    demand=ResourceDemand(cpu=0.0, mem_gb=0.0, disk_gb=0.0, net_mbps=0.0),
                    est_duration_s=1,
                ),
            ),
        )
        with pytest.raises(ClusterSizingError, match="zero on every resource"):
            size_cluster_for_target_utilization([zero_job], target_utilization=0.5, num_nodes=1)

    @pytest.mark.parametrize("bad_utilization", [0.0, -0.1, 1.5])
    def test_invalid_utilization_raises(self, bad_utilization: float) -> None:
        with pytest.raises(ClusterSizingError, match="target_utilization"):
            size_cluster_for_target_utilization(
                [_job(cpu=1.0)], target_utilization=bad_utilization, num_nodes=1
            )

    def test_invalid_num_nodes_raises(self) -> None:
        with pytest.raises(ClusterSizingError, match="num_nodes"):
            size_cluster_for_target_utilization(
                [_job(cpu=1.0)], target_utilization=0.5, num_nodes=0
            )
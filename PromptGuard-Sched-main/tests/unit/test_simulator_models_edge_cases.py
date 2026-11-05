"""Edge-case tests for simulator data-model validators and lookups."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.simulator.models import (
    AttackFamily,
    ClusterState,
    Job,
    NodeCapacity,
    ResourceDemand,
    Task,
    TaskEdge,
)


def _demand(*, cpu: float = 1.0, mem_gb: float = 1.0) -> ResourceDemand:
    return ResourceDemand(cpu=cpu, mem_gb=mem_gb, disk_gb=0.0, net_mbps=0.0)


def _task(task_id=None, *, name: str = "worker") -> Task:
    return Task(
        task_id=task_id or uuid4(),
        task_name=name,
        demand=_demand(),
        est_duration_s=1,
    )


def _node(node_id=None, *, zone: str = "zone-a") -> NodeCapacity:
    return NodeCapacity(node_id=node_id or uuid4(), zone=zone, capacity=_demand())


class TestTaskEdgeValidation:
    def test_rejects_self_dependency(self) -> None:
        task_id = uuid4()
        with pytest.raises(ValidationError, match="cannot depend on itself"):
            TaskEdge(
                parent_task_id=task_id,
                child_task_id=task_id,
                data_transfer_gb=0.0,
            )


class TestJobGraphValidation:
    @pytest.mark.parametrize("missing_side", ["parent", "child"])
    def test_rejects_edge_with_unknown_endpoint(self, missing_side: str) -> None:
        known = _task()
        unknown_id = uuid4()
        parent_id = unknown_id if missing_side == "parent" else known.task_id
        child_id = unknown_id if missing_side == "child" else known.task_id
        edge = TaskEdge(
            parent_task_id=parent_id,
            child_task_id=child_id,
            data_transfer_gb=0.0,
        )

        with pytest.raises(ValidationError, match="not present in this job's tasks"):
            Job(tenant_id=uuid4(), tasks=(known,), edges=(edge,))

    def test_rejects_dependency_cycle(self) -> None:
        first = _task(name="first")
        second = _task(name="second")
        edges = (
            TaskEdge(
                parent_task_id=first.task_id,
                child_task_id=second.task_id,
                data_transfer_gb=0.0,
            ),
            TaskEdge(
                parent_task_id=second.task_id,
                child_task_id=first.task_id,
                data_transfer_gb=0.0,
            ),
        )

        with pytest.raises(ValidationError, match="must be a DAG"):
            Job(tenant_id=uuid4(), tasks=(first, second), edges=edges)

    def test_rejects_attack_family_without_attack_ground_truth_flag(self) -> None:
        with pytest.raises(ValidationError, match="is_synthetic_attack is False"):
            Job(
                tenant_id=uuid4(),
                tasks=(_task(),),
                is_synthetic_attack=False,
                attack_payload_type=AttackFamily.DIRECT_OVERRIDE,
            )


class TestClusterStateValidationAndLookup:
    def test_rejects_duplicate_node_ids(self) -> None:
        duplicate_id = uuid4()
        with pytest.raises(ValidationError, match="duplicate node_id"):
            ClusterState(
                observed_at_s=0,
                nodes=(_node(duplicate_id, zone="zone-a"), _node(duplicate_id, zone="zone-b")),
            )

    def test_node_by_id_returns_matching_node(self) -> None:
        first = _node()
        second = _node()
        cluster = ClusterState(observed_at_s=0, nodes=(first, second))

        assert cluster.node_by_id(second.node_id) == second

    def test_node_by_id_raises_for_unknown_node(self) -> None:
        cluster = ClusterState(observed_at_s=0, nodes=(_node(),))
        missing_id = uuid4()

        with pytest.raises(KeyError, match="no node with node_id"):
            cluster.node_by_id(missing_id)

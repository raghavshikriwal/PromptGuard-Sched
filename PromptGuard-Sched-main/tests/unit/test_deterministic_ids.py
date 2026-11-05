"""Reproducibility tests: the same seed must yield identical ids/jobs/clusters."""

from __future__ import annotations

import pytest
from src.simulator.cluster_generator import size_cluster_for_target_utilization
from src.simulator.ids import deterministic_uuid
from src.simulator.trace_loader import SyntheticTraceGenerator

_NUM_JOBS = 20


class TestDeterministicUuid:
    def test_same_parts_same_uuid(self) -> None:
        assert deterministic_uuid("a", 1) == deterministic_uuid("a", 1)

    def test_different_parts_different_uuid(self) -> None:
        assert deterministic_uuid("a", 1) != deterministic_uuid("a", 2)

    def test_requires_a_part(self) -> None:
        with pytest.raises(ValueError):
            deterministic_uuid()


class TestSyntheticTraceGeneratorReproducibility:
    def test_same_seed_yields_identical_jobs(self) -> None:
        first = SyntheticTraceGenerator(seed=7).generate(_NUM_JOBS, injection_ratio=0.1)
        second = SyntheticTraceGenerator(seed=7).generate(_NUM_JOBS, injection_ratio=0.1)
        assert first == second

    def test_different_seed_yields_different_ids(self) -> None:
        first = SyntheticTraceGenerator(seed=1).generate(_NUM_JOBS)
        second = SyntheticTraceGenerator(seed=2).generate(_NUM_JOBS)
        assert {job.job_id for job in first}.isdisjoint({job.job_id for job in second})

    def test_ids_are_unique_within_and_across_generate_calls(self) -> None:
        generator = SyntheticTraceGenerator(seed=3)
        jobs = generator.generate(_NUM_JOBS) + generator.generate(_NUM_JOBS)
        assert len({job.job_id for job in jobs}) == 2 * _NUM_JOBS
        task_ids = [task.task_id for job in jobs for task in job.tasks]
        assert len(task_ids) == len(set(task_ids))


class TestClusterReproducibility:
    def test_same_jobs_yield_identical_cluster(self) -> None:
        jobs = SyntheticTraceGenerator(seed=5).generate(_NUM_JOBS)
        first = size_cluster_for_target_utilization(jobs, target_utilization=0.766, num_nodes=20)
        second = size_cluster_for_target_utilization(jobs, target_utilization=0.766, num_nodes=20)
        assert first == second
        assert len({node.node_id for node in first.nodes}) == 20

"""Unit tests for CSV trace ingestion and deterministic synthetic trace generation."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
import pytest

from src.simulator.models import AttackFamily
from src.simulator.trace_loader import (
    PREPROCESSED_TRACE_SCHEMA,
    GoogleClusterTraceLoader,
    SyntheticTraceGenerator,
    TraceFormatError,
)


def _trace_row(
    *,
    job_id: str,
    tenant_id: str,
    task_index: int,
    parent_task_index: int | None = None,
    deadline_s: int | None = 120,
    **overrides: object,
) -> dict[str, object]:
    """Return one valid preprocessed trace row with optional field overrides."""
    row: dict[str, object] = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "task_index": task_index,
        "task_name": f"task-{task_index}",
        "cpu_demand": 1.5 + task_index,
        "mem_demand_gb": 2.0 + task_index,
        "disk_demand_gb": 3.0 + task_index,
        "net_demand_mbps": 10.0 + task_index,
        "est_duration_s": 30 + task_index,
        "priority": 4,
        "deadline_s": deadline_s,
        "weight": 1.25,
        "description": "trace workload",
        "parent_task_index": parent_task_index,
        "data_transfer_gb": 0.5,
    }
    row.update(overrides)
    return row


def _write_trace(tmp_path: Path, rows: list[dict[str, object]]) -> str:
    path = tmp_path / "trace.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


class TestGoogleClusterTraceLoader:
    def test_loads_jobs_tasks_and_dependency_edges(self, tmp_path: Path) -> None:
        tenant_id = str(uuid4())
        rows = [
            _trace_row(job_id="job-a", tenant_id=tenant_id, task_index=0),
            _trace_row(
                job_id="job-a",
                tenant_id=tenant_id,
                task_index=1,
                parent_task_index=0,
                data_transfer_gb=2.75,
            ),
            _trace_row(
                job_id="job-b",
                tenant_id=str(uuid4()),
                task_index=0,
                deadline_s=None,
                description="second workload",
            ),
        ]

        jobs = GoogleClusterTraceLoader(_write_trace(tmp_path, rows)).load()

        assert len(jobs) == 2
        first = next(job for job in jobs if job.description == "trace workload")
        second = next(job for job in jobs if job.description == "second workload")
        assert first.tenant_id == UUID(tenant_id)
        assert first.priority == 4
        assert first.deadline_s == 120
        assert first.weight == pytest.approx(1.25)
        assert len(first.tasks) == 2
        assert first.tasks[0].task_name == "task-0"
        assert first.tasks[1].demand.cpu == pytest.approx(2.5)
        assert first.tasks[1].demand.mem_gb == pytest.approx(3.0)
        assert first.tasks[1].demand.disk_gb == pytest.approx(4.0)
        assert first.tasks[1].demand.net_mbps == pytest.approx(11.0)
        assert first.tasks[1].est_duration_s == 31
        assert len(first.edges) == 1
        assert first.edges[0].parent_task_id == first.tasks[0].task_id
        assert first.edges[0].child_task_id == first.tasks[1].task_id
        assert first.edges[0].data_transfer_gb == pytest.approx(2.75)
        assert second.deadline_s is None
        assert second.edges == ()

    def test_missing_file_raises_trace_format_error(self, tmp_path: Path) -> None:
        missing_path = tmp_path / "does-not-exist.csv"
        with pytest.raises(TraceFormatError, match="trace file not found"):
            GoogleClusterTraceLoader(missing_path).load()

    def test_missing_required_columns_are_reported(self, tmp_path: Path) -> None:
        path = tmp_path / "incomplete.csv"
        pd.DataFrame([{"job_id": "job-a", "tenant_id": str(uuid4())}]).to_csv(
            path, index=False
        )

        with pytest.raises(TraceFormatError, match="missing required columns") as error:
            GoogleClusterTraceLoader(path).load()

        assert "task_index" in str(error.value)
        assert "description" in str(error.value)

    @pytest.mark.parametrize(
        "field, conflicting_value",
        [
            ("tenant_id", str(uuid4())),
            ("priority", 5),
            ("deadline_s", 999),
            ("weight", 2.5),
            ("description", "different description"),
        ],
    )
    def test_inconsistent_job_level_fields_are_rejected(
        self,
        tmp_path: Path,
        field: str,
        conflicting_value: object,
    ) -> None:
        tenant_id = str(uuid4())
        second_row = _trace_row(job_id="job-a", tenant_id=tenant_id, task_index=1)
        second_row[field] = conflicting_value
        rows = [
            _trace_row(job_id="job-a", tenant_id=tenant_id, task_index=0),
            second_row,
        ]

        with pytest.raises(TraceFormatError, match=f"inconsistent values.*{field}"):
            GoogleClusterTraceLoader(_write_trace(tmp_path, rows)).load()

    def test_empty_valid_csv_returns_empty_job_list(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.csv"
        pd.DataFrame(columns=PREPROCESSED_TRACE_SCHEMA).to_csv(path, index=False)

        assert GoogleClusterTraceLoader(path).load() == []


class TestSyntheticTraceGeneratorValidation:
    def test_rejects_zero_tenants(self) -> None:
        with pytest.raises(ValueError, match="num_tenants must be >= 1"):
            SyntheticTraceGenerator(seed=1, num_tenants=0)

    @pytest.mark.parametrize(
        "duration_range, deadline_range, message",
        [
            ((0, 10), (60, 120), "duration_range_s"),
            ((30, 10), (60, 120), "duration_range_s"),
            ((30, 60), (0, 120), "deadline_range_s"),
            ((30, 60), (120, 60), "deadline_range_s"),
        ],
    )
    def test_rejects_invalid_duration_or_deadline_ranges(
        self,
        duration_range: tuple[int, int],
        deadline_range: tuple[int, int],
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            SyntheticTraceGenerator(
                seed=1,
                duration_range_s=duration_range,
                deadline_range_s=deadline_range,
            )

    def test_rejects_zero_jobs(self) -> None:
        with pytest.raises(ValueError, match="num_jobs must be >= 1"):
            SyntheticTraceGenerator(seed=1).generate(0)

    @pytest.mark.parametrize("task_range", [(0, 1), (2, 1)])
    def test_rejects_invalid_task_count_range(self, task_range: tuple[int, int]) -> None:
        with pytest.raises(ValueError, match="tasks_per_job"):
            SyntheticTraceGenerator(seed=1).generate(1, tasks_per_job=task_range)

    @pytest.mark.parametrize("ratio", [-0.01, 1.01])
    def test_rejects_invalid_injection_ratio(self, ratio: float) -> None:
        with pytest.raises(ValueError, match="injection_ratio"):
            SyntheticTraceGenerator(seed=1).generate(2, injection_ratio=ratio)


class TestSyntheticTraceGeneratorOutput:
    def test_single_task_jobs_have_no_edges(self) -> None:
        jobs = SyntheticTraceGenerator(seed=10).generate(3, tasks_per_job=(1, 1))

        assert all(len(job.tasks) == 1 for job in jobs)
        assert all(job.edges == () for job in jobs)
        assert all(not job.is_synthetic_attack for job in jobs)

    def test_injected_jobs_use_placeholder_and_valid_attack_ground_truth(self) -> None:
        jobs = SyntheticTraceGenerator(seed=11).generate(
            8, tasks_per_job=(2, 2), injection_ratio=1.0
        )

        assert all(job.is_synthetic_attack for job in jobs)
        assert all(job.attack_payload_type in set(AttackFamily) for job in jobs)
        assert all("SYNTHETIC ATTACK PLACEHOLDER" in job.description for job in jobs)
        assert all(len(job.edges) >= 1 for job in jobs)

    def test_injector_callback_receives_description_and_attack_family(self) -> None:
        received: list[tuple[str, AttackFamily]] = []

        def injector(description: str, family: AttackFamily) -> str:
            received.append((description, family))
            return f"{description} [test payload: {family.value}]"

        jobs = SyntheticTraceGenerator(seed=12).generate(
            4, injection_ratio=1.0, attack_payload_injector=injector
        )

        assert len(received) == 4
        assert all(description == "synthetic benign job" for description, _ in received)
        assert all(job.is_synthetic_attack for job in jobs)
        assert all("[test payload:" in job.description for job in jobs)
        assert all("PLACEHOLDER" not in job.description for job in jobs)

    def test_generated_task_dags_are_acyclic_and_edges_reference_job_tasks(self) -> None:
        jobs = SyntheticTraceGenerator(seed=13).generate(
            20, tasks_per_job=(3, 5), injection_ratio=0.0
        )

        for job in jobs:
            task_ids = {task.task_id for task in job.tasks}
            assert len(task_ids) == len(job.tasks)
            assert set(job.to_networkx().nodes) == task_ids
            assert all(edge.parent_task_id in task_ids for edge in job.edges)
            assert all(edge.child_task_id in task_ids for edge in job.edges)
            assert len(job.edges) >= len(job.tasks) - 1

    def test_generators_with_same_seed_produce_equal_jobs(self) -> None:
        first = SyntheticTraceGenerator(seed=14).generate(10, injection_ratio=0.2)
        second = SyntheticTraceGenerator(seed=14).generate(10, injection_ratio=0.2)

        assert first == second

"""Unit tests for the pure logic in `eval/metrics/baseline_metrics.py` and
`critical_path_duration_s` — the numbers every later ASR/CFD comparison is
built on, so their edge cases are pinned explicitly.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from eval.experiments.baseline_runner import critical_path_duration_s
from eval.metrics.baseline_metrics import (
    BaselineMetrics,
    _bottleneck_share,
    _compare,
    _jains_fairness_index,
    evaluate_against_reference,
)
from src.config import (
    BASELINE_REFERENCE_AVG_JCT_S,
    BASELINE_REFERENCE_CPU_UTILIZATION,
    BASELINE_REFERENCE_DRF_FAIRNESS,
    BASELINE_REFERENCE_SLA_VIOLATION_RATE,
)
from src.simulator.models import Job, ResourceDemand, Task, TaskEdge

_DEMAND = ResourceDemand(cpu=1.0, mem_gb=1.0, disk_gb=0.0, net_mbps=0.0)


def _task(duration_s: int) -> Task:
    return Task(task_name="t", demand=_DEMAND, est_duration_s=duration_s)


def _job(tasks: tuple[Task, ...], edges: tuple[TaskEdge, ...] = ()) -> Job:
    return Job(tenant_id=uuid4(), tasks=tasks, edges=edges)


def _edge(parent: Task, child: Task) -> TaskEdge:
    return TaskEdge(
        parent_task_id=parent.task_id, child_task_id=child.task_id, data_transfer_gb=0.0
    )


class TestCriticalPathDuration:
    def test_single_task(self) -> None:
        assert critical_path_duration_s(_job((_task(30),))) == pytest.approx(30.0)

    def test_chain_sums_durations(self) -> None:
        first, second = _task(10), _task(20)
        job = _job((first, second), (_edge(first, second),))
        assert critical_path_duration_s(job) == pytest.approx(30.0)

    def test_independent_tasks_run_in_parallel(self) -> None:
        job = _job((_task(10), _task(20)))
        assert critical_path_duration_s(job) == pytest.approx(20.0)

    def test_diamond_takes_the_longer_branch(self) -> None:
        root, short, long_, sink = _task(5), _task(1), _task(10), _task(5)
        job = _job(
            (root, short, long_, sink),
            (_edge(root, short), _edge(root, long_), _edge(short, sink), _edge(long_, sink)),
        )
        assert critical_path_duration_s(job) == pytest.approx(20.0)


class TestJainsFairnessIndex:
    def test_equal_ratios_are_perfectly_fair(self) -> None:
        assert _jains_fairness_index([0.5, 0.5, 0.5]) == pytest.approx(1.0)

    def test_empty_defaults_to_one(self) -> None:
        assert _jains_fairness_index([]) == 1.0

    def test_all_zero_defaults_to_one(self) -> None:
        assert _jains_fairness_index([0.0, 0.0]) == 1.0

    def test_one_job_hogging_is_one_over_n(self) -> None:
        assert _jains_fairness_index([1.0, 0.0]) == pytest.approx(0.5)


class TestBottleneckShare:
    def test_min_over_demanded_resources_only(self) -> None:
        demand = ResourceDemand(cpu=1.0, mem_gb=1.0, disk_gb=0.0, net_mbps=0.0)
        shares = {"cpu": 0.9, "mem_gb": 0.4, "disk_gb": 0.0, "net_mbps": 0.0}
        assert _bottleneck_share(shares, demand) == pytest.approx(0.4)

    def test_zero_demand_job_is_not_bottlenecked(self) -> None:
        zero = ResourceDemand(cpu=0.0, mem_gb=0.0, disk_gb=0.0, net_mbps=0.0)
        shares = {"cpu": 0.0, "mem_gb": 0.0, "disk_gb": 0.0, "net_mbps": 0.0}
        assert _bottleneck_share(shares, zero) == 1.0


class TestCompare:
    def test_inside_band_passes(self) -> None:
        assert _compare("m", 110.0, 100.0, 0.4).within_tolerance

    def test_outside_band_fails(self) -> None:
        assert not _compare("m", 141.0, 100.0, 0.4).within_tolerance

    def test_exact_boundary_passes(self) -> None:
        assert _compare("m", 140.0, 100.0, 0.4).within_tolerance


def _metrics(**overrides: float) -> BaselineMetrics:
    values: dict[str, float] = {
        "avg_jct_s": BASELINE_REFERENCE_AVG_JCT_S,
        "cpu_utilization": BASELINE_REFERENCE_CPU_UTILIZATION,
        "sla_violation_rate": BASELINE_REFERENCE_SLA_VIOLATION_RATE,
        "drf_fairness_index": BASELINE_REFERENCE_DRF_FAIRNESS,
    }
    values.update(overrides)
    return BaselineMetrics(
        experiment_id=uuid4(),
        jobs_evaluated=10,
        jobs_with_deadline=7,
        avg_jct_s=values["avg_jct_s"],
        cpu_utilization=values["cpu_utilization"],
        sla_violation_rate=values["sla_violation_rate"],
        drf_fairness_index=values["drf_fairness_index"],
    )


class TestEvaluateAgainstReference:
    def test_metrics_at_reference_pass(self) -> None:
        report = evaluate_against_reference(_metrics())
        assert report.passed
        assert "PASS" in report.render()

    def test_one_metric_out_of_range_fails_the_gate(self) -> None:
        report = evaluate_against_reference(_metrics(avg_jct_s=40000.0))
        assert not report.passed
        rendered = report.render()
        assert "FAIL" in rendered
        assert "OUT OF RANGE" in rendered

    def test_tolerance_is_adjustable(self) -> None:
        metrics = _metrics(avg_jct_s=BASELINE_REFERENCE_AVG_JCT_S * 1.5)
        assert not evaluate_against_reference(metrics).passed
        assert evaluate_against_reference(metrics, relative_tolerance=0.6).passed

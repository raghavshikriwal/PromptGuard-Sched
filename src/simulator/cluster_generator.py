"""Synthetic cluster-capacity generation (blueprint §7 `src/simulator/`).

`src/simulator/trace_loader.py` produces `Job` objects — tenant demand.
Neither loading path there produces a `ClusterState` — the preprocessed
trace schema (`PREPROCESSED_TRACE_SCHEMA`) is task/job-level only, and the
Google trace's actual per-machine capacity table is a separate join this
project does not require for the modular-monolith pipeline (blueprint §7.1:
`ClusterState` is a trusted, system-side input, sized however an experiment
needs it sized).

This module is the other half: given a set of `Job`s, size a `ClusterState`
to hit a *target aggregate utilization* if every job received exactly its
demand. That target is a direct experiment control — the baseline
validation gate (blueprint §13) needs to reproduce a CPU utilization
figure directionally close to the LLMSched reference (§11: 76.6%), and a
cluster sized independently of the job set's own aggregate demand would
make that comparison meaningless (either everything trivially fits, or
nothing does).

Deliberately NOT this module's job:
- Deciding which jobs are "active" for a run — `eval/experiments/` composes
  this with `SyntheticTraceGenerator`/`GoogleClusterTraceLoader` and passes
  in whichever job set it decided to schedule.
- Any tenant-authored content. Every field this module produces is
  system-side capacity (`NodeCapacity`), same trust class as
  `ClusterState` itself — see that model's own docstring.
"""

from __future__ import annotations

from src.simulator.models import ClusterState, Job, NodeCapacity, ResourceDemand

# Utilization must be in (0, 1]; 0 has no sensible "capacity sized to hit
# zero utilization" and would produce an unbounded/undefined cluster.
_MIN_TARGET_UTILIZATION: float = 1e-6
_MAX_TARGET_UTILIZATION: float = 1.0


class ClusterSizingError(ValueError):
    """Raised for invalid sizing inputs (empty job set, bad utilization)."""


def total_job_demand(jobs: list[Job]) -> ResourceDemand:
    """Sum of `Job.total_demand()` across every job in `jobs`.

    Thin wrapper kept here (rather than requiring every caller to fold
    `Job.total_demand()` itself) so `size_cluster_for_target_utilization`
    and `eval/metrics/` share one definition of "aggregate demand."
    """
    total = ResourceDemand(cpu=0.0, mem_gb=0.0, disk_gb=0.0, net_mbps=0.0)
    for job in jobs:
        total = total + job.total_demand()
    return total


def size_cluster_for_target_utilization(
    jobs: list[Job],
    *,
    target_utilization: float,
    num_nodes: int,
    observed_at_s: int = 0,
) -> ClusterState:
    """Build a `ClusterState` whose total capacity is `total_job_demand(jobs)
    / target_utilization`, split evenly across `num_nodes` homogeneous nodes.

    Args:
        jobs: the job set this cluster must be sized against. Must be
            non-empty and demand at least one unit of at least one
            resource — a cluster sized against zero aggregate demand is
            undefined (division by zero).
        target_utilization: the aggregate utilization every resource
            reaches if every job is granted exactly its full demand,
            e.g. `0.766` to reproduce the CPU-utilization axis of the
            LLMSched reference figure (blueprint §11). Must be in
            `(0.0, 1.0]`.
        num_nodes: how many homogeneous `NodeCapacity` nodes to split the
            sized total across. Must be >= 1. Node count does not affect
            aggregate utilization (only `src/ilp/`'s per-job feasibility
            against total capacity, and DRF's, are utilization-sensitive
            in this codebase today — see both modules' scope notes) but
            is exposed here for experiment realism/reporting.
        observed_at_s: passed through to `ClusterState.observed_at_s`.

    Raises:
        ClusterSizingError: `jobs` is empty, demands nothing on any
            resource, `target_utilization` is out of `(0.0, 1.0]`, or
            `num_nodes < 1`.
    """
    if not jobs:
        raise ClusterSizingError("cannot size a cluster against an empty job set")
    if num_nodes < 1:
        raise ClusterSizingError(f"num_nodes must be >= 1, got {num_nodes}")
    if not _MIN_TARGET_UTILIZATION <= target_utilization <= _MAX_TARGET_UTILIZATION:
        raise ClusterSizingError(
            f"target_utilization must be in (0.0, 1.0], got {target_utilization:g}"
        )

    demand = total_job_demand(jobs)
    if (demand.cpu, demand.mem_gb, demand.disk_gb, demand.net_mbps) == (0.0, 0.0, 0.0, 0.0):
        raise ClusterSizingError(
            "job set demands zero on every resource — nothing to size against"
        )

    total_capacity = ResourceDemand(
        cpu=demand.cpu / target_utilization,
        mem_gb=demand.mem_gb / target_utilization,
        disk_gb=demand.disk_gb / target_utilization,
        net_mbps=demand.net_mbps / target_utilization,
    )
    per_node_capacity = ResourceDemand(
        cpu=total_capacity.cpu / num_nodes,
        mem_gb=total_capacity.mem_gb / num_nodes,
        disk_gb=total_capacity.disk_gb / num_nodes,
        net_mbps=total_capacity.net_mbps / num_nodes,
    )

    nodes = tuple(
        NodeCapacity(zone=f"zone-{index % 3}", capacity=per_node_capacity)
        for index in range(num_nodes)
    )
    return ClusterState(observed_at_s=observed_at_s, nodes=nodes)
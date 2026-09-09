"""Cluster/trace simulation (blueprint §7 `src/simulator/`).

Public API re-exported here so callers write `from src.simulator import
Job, ClusterState` rather than reaching into submodules directly — the
same pattern `src/encoder/__init__.py`, `src/llm/__init__.py`,
`src/ilp/__init__.py`, and `src/scheduler/__init__.py` already use.
"""

from src.simulator.cluster_generator import (
    ClusterSizingError,
    size_cluster_for_target_utilization,
    total_job_demand,
)
from src.simulator.models import (
    AttackFamily,
    ClusterState,
    Job,
    NodeCapacity,
    ResourceDemand,
    Task,
    TaskEdge,
)
from src.simulator.trace_loader import (
    GoogleClusterTraceLoader,
    SyntheticTraceGenerator,
    TraceFormatError,
)

__all__ = [
    "AttackFamily",
    "ClusterState",
    "ClusterSizingError",
    "GoogleClusterTraceLoader",
    "Job",
    "NodeCapacity",
    "ResourceDemand",
    "SyntheticTraceGenerator",
    "Task",
    "TaskEdge",
    "TraceFormatError",
    "size_cluster_for_target_utilization",
    "total_job_demand",
]

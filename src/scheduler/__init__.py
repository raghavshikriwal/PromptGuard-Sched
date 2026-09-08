"""Pipeline orchestration stage (blueprint §7 `src/scheduler/`).

Public API re-exported here so callers write `from src.scheduler import
SchedulingPipeline` rather than reaching into submodules directly.
"""

from src.scheduler.fairness import (
    DrfEntitlementError,
    compute_delta_j,
    compute_drf_entitlements,
    dominant_resource_share,
)
from src.scheduler.pipeline import ScheduleOutcome, SchedulingPipeline

__all__ = [
    "DrfEntitlementError",
    "ScheduleOutcome",
    "SchedulingPipeline",
    "compute_delta_j",
    "compute_drf_entitlements",
    "dominant_resource_share",
]

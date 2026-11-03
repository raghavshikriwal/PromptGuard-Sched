"""Pipeline orchestration stage (blueprint §7 `src/scheduler/`).

Public API re-exported here so callers write `from src.scheduler import
SchedulingPipeline` rather than reaching into submodules directly.

`pipeline` is imported lazily (PEP 562). `src.anomaly.check` imports
`src.scheduler.fairness`, and `pipeline` imports `src.anomaly.check`; an eager
import of `pipeline` here made `import src.anomaly` fail with a circular
import. Lazy loading keeps `from src.scheduler import SchedulingPipeline`
working while `src.scheduler.fairness` stays a cheap leaf import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.scheduler.fairness import (
    DrfEntitlementError,
    compute_delta_j,
    compute_drf_entitlements,
    dominant_resource_share,
)

if TYPE_CHECKING:
    from src.scheduler.pipeline import ScheduleOutcome, SchedulingPipeline

__all__ = [
    "DrfEntitlementError",
    "ScheduleOutcome",
    "SchedulingPipeline",
    "compute_delta_j",
    "compute_drf_entitlements",
    "dominant_resource_share",
]

_LAZY = {"ScheduleOutcome", "SchedulingPipeline"}


def __getattr__(name: str) -> object:
    if name in _LAZY:
        from src.scheduler import pipeline

        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

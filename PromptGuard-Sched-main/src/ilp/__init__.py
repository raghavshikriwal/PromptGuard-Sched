"""ILP allocation refinement stage (blueprint §7 `src/ilp/`).

Public API re-exported here so callers write `from src.ilp import
IlpAllocationRefiner` rather than reaching into `refine` directly.
"""

from src.ilp.refine import (
    RESOURCE_FIELDS,
    AllocationDecision,
    IlpAllocationRefiner,
    IlpRefinementError,
)

__all__ = [
    "RESOURCE_FIELDS",
    "AllocationDecision",
    "IlpAllocationRefiner",
    "IlpRefinementError",
]

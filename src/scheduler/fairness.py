
"""DRF entitlement and delta(J), the formal security metric.

Weighted Dominant Resource Fairness is computed using progressive filling.
All active jobs increase their dominant shares at rates proportional to
their weights. When a resource becomes saturated, only jobs consuming that
resource are frozen. Other jobs continue receiving their fair allocation.

All inputs are trusted scheduler-side resource data.
Tenant-authored text is never read by this module.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from uuid import UUID

from src.simulator.models import ResourceDemand

RESOURCE_FIELDS: tuple[str, ...] = ("cpu", "mem_gb", "disk_gb", "net_mbps")

_EPS: float = 1e-9


class DrfEntitlementError(RuntimeError):
    """Raised for malformed inputs or an invalid DRF allocation."""


def dominant_resource_share(
    amount: ResourceDemand,
    capacity: ResourceDemand,
) -> float:
    """Return max(amount[r] / capacity[r]) over positive-demand resources.

    Returns zero for zero demand and infinity when positive demand
    exists for a resource with zero capacity.
    """
    ratios = []

    for field in RESOURCE_FIELDS:
        resource_amount = getattr(amount, field)

        if resource_amount <= _EPS:
            continue

        resource_capacity = getattr(capacity, field)

        ratios.append(
            resource_amount / resource_capacity
            if resource_capacity > _EPS
            else float("inf")
        )

    return max(ratios) if ratios else 0.0


def compute_drf_entitlements(
    demands: Mapping[UUID, ResourceDemand],
    weights: Mapping[UUID, float],
    capacity: ResourceDemand,
) -> dict[UUID, float]:
    """Compute weighted DRF dominant-share entitlements.

    Each job has a normalized allocation fraction x_i in [0, 1].
    Its dominant share is x_i * d_i, where d_i is its dominant
    resource demand divided by cluster capacity.

    Progressive filling increases x_i at rate weight_i / d_i.
    Jobs consuming a saturated resource are frozen; other jobs continue.
    """
    if demands.keys() != weights.keys():
        raise DrfEntitlementError(
            "demands and weights must share the same set of job_ids"
        )

    for job_id, weight in weights.items():
        if not math.isfinite(weight) or weight <= _EPS:
            raise DrfEntitlementError(
                f"job {job_id}: weight must be finite and > 0, got {weight!r}"
            )

    for field in RESOURCE_FIELDS:
        value = getattr(capacity, field)
        if not math.isfinite(value) or value < 0:
            raise DrfEntitlementError(
                f"cluster capacity for {field} must be finite and non-negative"
            )

    for job_id, demand in demands.items():
        for field in RESOURCE_FIELDS:
            value = getattr(demand, field)
            if not math.isfinite(value) or value < 0:
                raise DrfEntitlementError(
                    f"job {job_id}: demand for {field} must be finite "
                    "and non-negative"
                )

    entitlement: dict[UUID, float] = {}
    active: set[UUID] = set()

    dominant_ratios: dict[UUID, float] = {}

    for job_id, demand in demands.items():
        ratio = dominant_resource_share(demand, capacity)

        if ratio == float("inf"):
            raise DrfEntitlementError(
                f"job {job_id}: demands a resource with zero cluster capacity"
            )

        dominant_ratios[job_id] = ratio

        if ratio <= _EPS:
            entitlement[job_id] = 0.0
        else:
            active.add(job_id)

    remaining_capacity = {
        field: float(getattr(capacity, field))
        for field in RESOURCE_FIELDS
    }

    # Allocation fractions are retained between progressive-filling rounds.
    shares = {job_id: 0.0 for job_id in active}

    while active:
        rates = {
            job_id: weights[job_id] / dominant_ratios[job_id]
            for job_id in active
        }

        # Determine how far all active jobs can increase before the
        # first job is fully served or a resource becomes saturated.
        limits: list[float] = []

        for job_id in active:
            limits.append((1.0 - shares[job_id]) / rates[job_id])

        resource_limits: dict[str, float] = {}

        for field in RESOURCE_FIELDS:
            resource_rate = sum(
                rates[job_id] * getattr(demands[job_id], field)
                for job_id in active
            )

            if resource_rate > _EPS:
                limit = max(0.0, remaining_capacity[field]) / resource_rate
                resource_limits[field] = limit
                limits.append(limit)

        if not limits:
            raise DrfEntitlementError(
                "progressive filling could not find a limiting event"
            )

        increment = min(limits)

        if not math.isfinite(increment) or increment < 0:
            raise DrfEntitlementError(
                f"invalid progressive-filling increment: {increment!r}"
            )

        # Advance every active job by the same weighted dominant-share
        # increment. Do not reset previously accumulated shares.
        for job_id in active:
            shares[job_id] = min(
                1.0,
                shares[job_id] + rates[job_id] * increment,
            )

        # Account for the new allocations of every active job.
        for field in RESOURCE_FIELDS:
            consumed = sum(
                rates[job_id]
                * increment
                * getattr(demands[job_id], field)
                for job_id in active
            )

            remaining_capacity[field] = max(
                0.0,
                remaining_capacity[field] - consumed,
            )

        tolerance = max(1e-10, abs(increment) * 1e-8)

        # Jobs reaching their complete demand are finished.
        frozen = {
            job_id
            for job_id in active
            if shares[job_id] >= 1.0 - 1e-8
        }

        # Freeze only jobs consuming a resource that became saturated.
        for field, resource_limit in resource_limits.items():
            if math.isclose(
                resource_limit,
                increment,
                rel_tol=1e-8,
                abs_tol=tolerance,
            ):
                for job_id in active:
                    if getattr(demands[job_id], field) > _EPS:
                        frozen.add(job_id)

        if not frozen:
            raise DrfEntitlementError(
                "progressive filling reached a limiting event "
                "without freezing any job"
            )

        for job_id in frozen:
            entitlement[job_id] = (
                shares[job_id] * dominant_ratios[job_id]
            )

        active.difference_update(frozen)

    return entitlement


def compute_delta_j(
    allocated_dominant_share: float,
    entitlement: float,
) -> float | None:
    """Compute delta(J) = (allocated(J) - e_J) / e_J.

    Returns None when entitlement is approximately zero, matching
    the NULLIF guard in the persisted database expression.
    """
    if entitlement <= _EPS:
        return None

    return (allocated_dominant_share - entitlement) / entitlement

"""DRF entitlement and Δ(J) — the formal security metric (blueprint §4).

    Δ(J) = (allocated(J) - e_J) / e_J

`e_J` is job J's **DRF fairness-neutral entitlement**: the dominant share
it would receive under multi-resource max-min fair sharing (Dominant
Resource Fairness, Ghodsi et al., NSDI 2011) among the jobs concurrently
competing for the cluster — computed entirely from trusted inputs (job
weights, resource demands, cluster capacity; blueprint §5: "DRF
calculation" is trusted, system-side). No tenant-authored text is read
anywhere in this module.

Blueprint §15 flags this as the single highest-stakes correctness
requirement in the codebase ("`delta_j` correctness is the single thing
the whole ASR metric's credibility rests on"), so `compute_drf_entitlements`
deliberately does not hand-derive a closed-form fluid/progressive-filling
formula (easy to get subtly wrong at multi-resource saturation events).
Instead it solves the equivalent iterative max-min-fair LP with PuLP/CBC —
the same solver dependency `src/ilp/refine.py` already uses — which is
correct by construction: at each round, maximizing a single shared
"fair-share rate" `t` subject to `x_i = w_i * t / dominant_ratio_i` and
per-resource capacity constraints is exactly one round of progressive
filling; jobs that hit `x_i == 1` (fully served) or that are only bounded
by a shared saturated resource are frozen, and the loop repeats on the
remaining active jobs with reduced capacity until none are left.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pulp

from src.simulator.models import ResourceDemand

RESOURCE_FIELDS: tuple[str, ...] = ("cpu", "mem_gb", "disk_gb", "net_mbps")

_EPS: float = 1e-9
_FAIR_SHARE_SOLVER_TIME_LIMIT_S: int = 5


class DrfEntitlementError(RuntimeError):
    """Raised for malformed inputs or a solver failure while computing
    DRF entitlements — never silently returns a wrong number.
    """


def dominant_resource_share(amount: ResourceDemand, capacity: ResourceDemand) -> float:
    """`max_r(amount_r / capacity_r)` over resources where `amount_r > 0`.

    Used two ways in this codebase: as a job's *demand* ratio against total
    cluster capacity (its "dominant resource" identification, the `d_i*`
    used inside `compute_drf_entitlements`), and as the *achieved* dominant
    share of a finalized `AllocationDecision.allocated` — i.e. `allocated(J)`
    in the Δ(J) formula. Returns `0.0` for a zero-demand input (no resource
    to be dominant in) and `math.inf` if some resource has positive amount
    but zero capacity (an infeasible cluster configuration for that
    resource — callers should not silently treat this as "small").
    """
    ratios = []
    for field in RESOURCE_FIELDS:
        resource_amount = getattr(amount, field)
        if resource_amount <= _EPS:
            continue
        resource_capacity = getattr(capacity, field)
        ratios.append(resource_amount / resource_capacity if resource_capacity > _EPS else float("inf"))
    return max(ratios) if ratios else 0.0


def compute_drf_entitlements(
    demands: Mapping[UUID, ResourceDemand],
    weights: Mapping[UUID, float],
    capacity: ResourceDemand,
) -> dict[UUID, float]:
    """Weighted multi-resource DRF entitlement `e_J` for every job in `demands`.

    Args:
        demands: `job_id -> total resource demand` for every job concurrently
            competing for `capacity` (typically `Job.total_demand()` for
            each job the scheduler currently considers active — see
            `src/scheduler/pipeline.py`).
        weights: `job_id -> Job.weight`, same key set as `demands`.
        capacity: total cluster capacity (`ClusterState.total_capacity()`).
            Every resource with positive demand from any job must have
            strictly positive capacity, or the cluster cannot admit that
            job at all — this raises rather than returning a misleading 0.

    Returns:
        `job_id -> e_J` (dominant-share entitlement) for every key in
        `demands`. A job with zero demand on every resource gets `e_J = 0.0`
        by definition (it has no dominant resource to hold an entitlement
        in) and never competes for capacity.

    Raises:
        DrfEntitlementError: `demands` and `weights` have different key
            sets, a weight is not strictly positive, or CBC fails to solve
            a round's fair-share LP.
    """
    if demands.keys() != weights.keys():
        raise DrfEntitlementError("demands and weights must share the same set of job_ids")
    for job_id, weight in weights.items():
        if weight <= _EPS:
            raise DrfEntitlementError(f"job {job_id}: weight must be > 0, got {weight:g}")

    entitlement: dict[UUID, float] = {}
    active: set[UUID] = set()
    for job_id, demand in demands.items():
        if dominant_resource_share(demand, capacity) <= _EPS:
            entitlement[job_id] = 0.0
        else:
            active.add(job_id)

    remaining_capacity = {field: getattr(capacity, field) for field in RESOURCE_FIELDS}

    while active:
        dominant_ratio = {job_id: dominant_resource_share(demands[job_id], capacity) for job_id in active}
        if any(ratio == float("inf") for ratio in dominant_ratio.values()):
            offending = next(jid for jid, r in dominant_ratio.items() if r == float("inf"))
            raise DrfEntitlementError(
                f"job {offending}: demands a resource with zero cluster capacity — "
                "cluster cannot admit this job at any positive share"
            )

        frozen = _solve_fair_share_round(
            active=active,
            demands=demands,
            weights=weights,
            dominant_ratio=dominant_ratio,
            remaining_capacity=remaining_capacity,
            entitlement=entitlement,
        )
        active -= frozen

    return entitlement


def _solve_fair_share_round(
    *,
    active: set[UUID],
    demands: Mapping[UUID, ResourceDemand],
    weights: Mapping[UUID, float],
    dominant_ratio: Mapping[UUID, float],
    remaining_capacity: dict[str, float],
    entitlement: dict[UUID, float],
) -> set[UUID]:
    """One round of progressive filling, solved as an LP: maximize the
    shared fair-share rate `t` such that every active job's granted
    fraction `x_i = w_i * t / dominant_ratio_i` stays within `[0, 1]` and
    within remaining per-resource capacity. Mutates `entitlement` and
    `remaining_capacity` in place; returns the set of job_ids frozen this
    round (removed from `active` by the caller).
    """
    problem = pulp.LpProblem("drf_fair_share_round", pulp.LpMaximize)
    t = pulp.LpVariable("t", lowBound=0.0)
    share_vars = {job_id: pulp.LpVariable(f"x_{job_id.hex}", lowBound=0.0, upBound=1.0) for job_id in active}

    problem += t
    for job_id in active:
        rate = weights[job_id] / dominant_ratio[job_id]
        problem += share_vars[job_id] == rate * t
    for field in RESOURCE_FIELDS:
        consumption = pulp.lpSum(
            share_vars[job_id] * getattr(demands[job_id], field) for job_id in active
        )
        problem += consumption <= remaining_capacity[field]

    status_code = problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=_FAIR_SHARE_SOLVER_TIME_LIMIT_S))
    status = pulp.LpStatus[status_code]
    if status != "Optimal":
        raise DrfEntitlementError(
            f"fair-share round: CBC returned status={status!r} (expected 'Optimal') "
            f"for {len(active)} active job(s)"
        )

    share_values = {job_id: _clamp_unit(share_vars[job_id].value()) for job_id in active}
    fully_served = {job_id for job_id, share in share_values.items() if share >= 1.0 - 1e-6}
    frozen = fully_served if fully_served else set(active)

    for job_id in frozen:
        entitlement[job_id] = share_values[job_id] * dominant_ratio[job_id]
    for field in RESOURCE_FIELDS:
        consumed = sum(share_values[job_id] * getattr(demands[job_id], field) for job_id in frozen)
        remaining_capacity[field] = max(0.0, remaining_capacity[field] - consumed)

    return frozen


def _clamp_unit(value: float | None) -> float:
    """Guard against CBC's float-epsilon overshoot past `[0, 1]`, same
    rationale as `src/ilp/refine.py`'s `_clamp_share`.
    """
    if value is None:
        return 0.0
    return max(0.0, min(1.0, value))


def compute_delta_j(allocated_dominant_share: float, entitlement: float) -> float | None:
    """`Δ(J) = (allocated(J) - e_J) / e_J` (blueprint §4).

    Returns `None` when `entitlement` is ~0 — mirrors the `NULLIF(...)`
    guard on the `delta_j` generated column in `db/migrations/models.py`,
    so a zero-entitlement edge case (a job with no dominant resource) is
    represented the same way in Python as it is in the persisted schema,
    rather than raising `ZeroDivisionError` or silently returning `0.0`.
    """
    if entitlement <= _EPS:
        return None
    return (allocated_dominant_share - entitlement) / entitlement

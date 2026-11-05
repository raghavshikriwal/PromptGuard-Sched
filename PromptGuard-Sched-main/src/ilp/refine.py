
"""ILP allocation refinement (blueprint §7).

The LLM proposal is an untrusted allocation target. This module solves a
linear program to find the closest capacity-feasible allocation.

Security invariant:
    0 <= allocated_share[r] <= proposal_share[r]

The proposal is a hard upper bound. The ILP must never increase a resource
share above the proposal supplied to it, preserving upstream anomaly caps.

    minimize   sum_r |x_r - proposal_r|
    subject to x_r * demand_r <= available_capacity_r
               0 <= x_r <= proposal_r

Absolute deviations are linearized using auxiliary variables.

Capacity scope:
- By default, allocation is bounded by total cluster capacity.
- Concurrent scheduling may supply the remaining available capacity.
- Available capacity cannot exceed total cluster capacity.
"""

from __future__ import annotations

from math import isfinite
from uuid import UUID

import pulp
from pydantic import BaseModel, Field

from src.llm.schema import AllocationProposal
from src.simulator.models import ClusterState, Job, ResourceDemand


RESOURCE_FIELDS: tuple[str, ...] = ("cpu", "mem_gb", "disk_gb", "net_mbps")

ILP_SOLVER_TIME_LIMIT_S: int = 5

_SHARE_LOWER_BOUND: float = 0.0
_SHARE_UPPER_BOUND: float = 1.0
_FEASIBILITY_EPS: float = 1e-9


class IlpRefinementError(RuntimeError):
    """Raised when the ILP cannot produce a valid allocation."""


class AllocationDecision(BaseModel):
    """Frozen output contract for the ILP allocation stage."""

    model_config = {"frozen": True}

    trace_id: UUID
    job_id: UUID
    allocated: ResourceDemand

    allocated_shares: dict[str, float] = Field(
        description="Per-resource fraction of demand granted."
    )
    proposed_shares: dict[str, float] = Field(
        description="Original proposal, retained for audit."
    )
    objective_value: float = Field(
        description="Total absolute deviation of the returned allocation."
    )
    solver_status: str


class IlpAllocationRefiner:
    """Find a feasible allocation without exceeding the supplied proposal.

    min_share is an anti-starvation lower-bound preference. It is limited by
    both available capacity and the proposal security cap.
    """

    def __init__(self, min_share: float = 0.0) -> None:
        if not isfinite(min_share) or not 0.0 <= min_share <= 1.0:
            raise ValueError("min_share must be within [0.0, 1.0]")

        self._min_share = min_share

    def _floor_for(self, demand: float, available: float) -> float:
        """Return the anti-starvation floor supported by available capacity."""
        if demand <= _FEASIBILITY_EPS:
            return _SHARE_LOWER_BOUND

        return max(
            _SHARE_LOWER_BOUND,
            min(self._min_share, available / demand),
        )

    def refine(
        self,
        *,
        job: Job,
        cluster_state: ClusterState,
        proposal: AllocationProposal,
        trace_id: UUID,
        available_capacity: ResourceDemand | None = None,
    ) -> AllocationDecision:
        """Refine a proposal into a capacity-feasible allocation.

        Raises:
            ValueError:
                If supplied available capacity exceeds cluster capacity.

            IlpRefinementError:
                If the problem is infeasible, CBC fails, or the solver
                returns missing or invalid decision-variable values.
        """
        demand = job.total_demand()
        total_capacity = cluster_state.total_capacity()

        requested_capacity = (
            available_capacity
            if available_capacity is not None
            else total_capacity
        )

        _validate_available_capacity(requested_capacity, total_capacity)

        # Never let a tolerance-sized excess in available_capacity become
        # an allocation above the actual cluster capacity.
        capacity = ResourceDemand(
            cpu=min(requested_capacity.cpu, total_capacity.cpu),
            mem_gb=min(requested_capacity.mem_gb, total_capacity.mem_gb),
            disk_gb=min(requested_capacity.disk_gb, total_capacity.disk_gb),
            net_mbps=min(requested_capacity.net_mbps, total_capacity.net_mbps),
        )

        proposed_shares = _proposal_shares(proposal)

        problem = pulp.LpProblem(
            f"ilp_refine_{job.job_id.hex}",
            pulp.LpMinimize,
        )

        share_vars: dict[str, pulp.LpVariable] = {}
        deviation_vars: dict[str, pulp.LpVariable] = {}

        for field in RESOURCE_FIELDS:
            resource_demand = getattr(demand, field)
            resource_capacity = getattr(capacity, field)
            proposal_cap = proposed_shares[field]

            # The proposal cap always takes precedence over min_share.
            floor = min(
                self._floor_for(resource_demand, resource_capacity),
                proposal_cap,
            )

            share_vars[field] = pulp.LpVariable(
                f"x_{field}",
                lowBound=floor,
                upBound=proposal_cap,
            )

            deviation_vars[field] = pulp.LpVariable(
                f"dev_{field}",
                lowBound=0.0,
            )

        problem += pulp.lpSum(deviation_vars.values())

        for field in RESOURCE_FIELDS:
            target = proposed_shares[field]
            share = share_vars[field]
            deviation = deviation_vars[field]

            # Linearize absolute deviation.
            problem += deviation >= share - target
            problem += deviation >= target - share

            resource_demand = getattr(demand, field)
            resource_capacity = getattr(capacity, field)
            cluster_capacity = getattr(total_capacity, field)

            if resource_demand > _FEASIBILITY_EPS:
                if cluster_capacity <= _FEASIBILITY_EPS:
                    raise IlpRefinementError(
                        f"job {job.job_id} demands {field}="
                        f"{resource_demand:g}, but cluster capacity is "
                        f"{cluster_capacity:g}; no positive allocation "
                        "is feasible."
                    )

                problem += (
                    share * resource_demand <= resource_capacity
                )

        try:
            status_code = problem.solve(
                pulp.PULP_CBC_CMD(
                    msg=False,
                    timeLimit=ILP_SOLVER_TIME_LIMIT_S,
                )
            )
        except pulp.PulpSolverError as exc:
            raise IlpRefinementError(
                f"job {job.job_id}: CBC solver execution failed: {exc}"
            ) from exc

        status = pulp.LpStatus.get(
            status_code,
            f"Unknown ({status_code})",
        )

        if status != "Optimal":
            raise IlpRefinementError(
                f"job {job.job_id}: CBC returned status={status!r}; "
                f"expected 'Optimal' within "
                f"{ILP_SOLVER_TIME_LIMIT_S}s."
            )

        # Validate and clamp every solver value independently.
        allocated_shares: dict[str, float] = {}

        for field in RESOURCE_FIELDS:
            resource_demand = getattr(demand, field)
            resource_capacity = getattr(capacity, field)
            proposal_cap = proposed_shares[field]

            # Enforce both the proposal security cap and the capacity cap
            # after solving, protecting against solver floating-point error.
            capacity_share_cap = (
                resource_capacity / resource_demand
                if resource_demand > _FEASIBILITY_EPS
                else _SHARE_UPPER_BOUND
            )

            effective_cap = min(
                proposal_cap,
                capacity_share_cap,
                _SHARE_UPPER_BOUND,
            )

            allocated_shares[field] = _clamp_share(
                share_vars[field].value(),
                upper_bound=effective_cap,
            )

        allocated = ResourceDemand(
            cpu=allocated_shares["cpu"] * demand.cpu,
            mem_gb=allocated_shares["mem_gb"] * demand.mem_gb,
            disk_gb=allocated_shares["disk_gb"] * demand.disk_gb,
            net_mbps=allocated_shares["net_mbps"] * demand.net_mbps,
        )

        # Final independent invariant checks.
        for field in RESOURCE_FIELDS:
            actual_share = allocated_shares[field]
            proposal_cap = proposed_shares[field]

            if actual_share < _SHARE_LOWER_BOUND:
                raise IlpRefinementError(
                    f"job {job.job_id}: negative allocation share "
                    f"returned for {field}: {actual_share}"
                )

            if actual_share > proposal_cap:
                raise IlpRefinementError(
                    f"job {job.job_id}: proposal cap violated for {field}: "
                    f"{actual_share} > {proposal_cap}"
                )

            actual_amount = getattr(allocated, field)
            available_amount = getattr(capacity, field)

            if actual_amount > available_amount + _FEASIBILITY_EPS:
                raise IlpRefinementError(
                    f"job {job.job_id}: capacity constraint violated "
                    f"for {field}: {actual_amount} > {available_amount}"
                )

        # Calculate the objective from the actual returned allocation.
        objective_value = sum(
            abs(allocated_shares[field] - proposed_shares[field])
            for field in RESOURCE_FIELDS
        )

        return AllocationDecision(
            trace_id=trace_id,
            job_id=job.job_id,
            allocated=allocated,
            allocated_shares=allocated_shares,
            proposed_shares=proposed_shares,
            objective_value=objective_value,
            solver_status=status,
        )


def _validate_available_capacity(
    available: ResourceDemand,
    total: ResourceDemand,
) -> None:
    """Ensure available capacity is a subset of cluster capacity."""
    for field in RESOURCE_FIELDS:
        available_amount = getattr(available, field)
        total_amount = getattr(total, field)

        if available_amount > total_amount + _FEASIBILITY_EPS:
            raise ValueError(
                f"available_capacity.{field}={available_amount:g} "
                f"exceeds cluster total {total_amount:g}"
            )


def _proposal_shares(
    proposal: AllocationProposal,
) -> dict[str, float]:
    """Map proposal share fields to ResourceDemand field names."""
    return {
        "cpu": proposal.cpu_share,
        "mem_gb": proposal.mem_share,
        "disk_gb": proposal.disk_share,
        "net_mbps": proposal.net_share,
    }


def _clamp_share(
    value: float | None,
    *,
    upper_bound: float = _SHARE_UPPER_BOUND,
) -> float:
    """Clamp a valid solver result to its permitted share interval.

    Missing or non-finite solver values are errors. They must never be
    silently converted into zero allocations.
    """
    if value is None:
        raise IlpRefinementError(
            "CBC returned an optimal status but a decision variable "
            "has no value."
        )

    if not isfinite(value):
        raise IlpRefinementError(
            f"CBC returned a non-finite decision-variable value: {value!r}"
        )

    if not isfinite(upper_bound) or not (
        _SHARE_LOWER_BOUND <= upper_bound <= _SHARE_UPPER_BOUND
    ):
        raise ValueError(
            f"upper_bound must be within "
            f"[{_SHARE_LOWER_BOUND}, {_SHARE_UPPER_BOUND}]"
        )

    return max(
        _SHARE_LOWER_BOUND,
        min(upper_bound, value),
    )

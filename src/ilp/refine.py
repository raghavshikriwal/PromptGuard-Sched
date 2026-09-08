"""ILP allocation refinement (blueprint §7 `src/ilp/`, "PuLP/CBC, finalizes
allocation").

`src/llm/` produces an `AllocationProposal` — a set of *shares* the model
recommends granting, with no guarantee those shares are jointly feasible
against real cluster capacity (the model never sees an optimizer's
constraints, only prose). This module is the trusted, system-side stage
(blueprint §5: "solver" is trusted) that takes that proposal as a *target*
and solves a small linear program to find the closest feasible allocation:

    minimize   sum_r |x_r - proposal_r|          (deviation from proposal)
    subject to x_r * demand_r <= capacity_r        for each resource r
               0 <= x_r <= 1                       for each resource r

`|x_r - proposal_r|` is linearized with an auxiliary deviation variable per
resource (`dev_r >= x_r - proposal_r`, `dev_r >= proposal_r - x_r`) so the
whole thing stays a linear program solvable by CBC, rather than needing a
quadratic solver for a squared-deviation objective.

Scope note (intentionally not solved here): this formulation bounds one
job's allocation against total cluster capacity, not against capacity
*remaining after other concurrently-scheduled jobs*. Multi-job concurrent
capacity accounting is `eval/experiments/`'s job when it batches jobs from
a trace window — this module's contract is "one job's proposal in, one
job's feasible allocation out," matching `src/llm/`'s and `src/encoder/`'s
per-job scope.
"""

from __future__ import annotations

from uuid import UUID

import pulp
from pydantic import BaseModel, Field

from src.llm.schema import AllocationProposal
from src.simulator.models import ClusterState, Job, ResourceDemand

# `ResourceDemand`'s field names, in a fixed iteration order. Deliberately
# not re-derived via reflection (`ResourceDemand.model_fields`), so a
# rename there fails loudly here rather than silently reordering resources.
# `src/scheduler/fairness.py` defines the same tuple independently rather
# than importing it from here — `src/scheduler/` composes `src/ilp/`, so a
# dependency in the other direction would invert that layering.
RESOURCE_FIELDS: tuple[str, ...] = ("cpu", "mem_gb", "disk_gb", "net_mbps")

# CBC wall-clock budget per job. Blueprint §15 load/latency testing (Locust/
# k6 against concurrent `POST /jobs`) needs this bounded — an unconstrained
# solve on a pathological instance would starve P99 latency for every other
# in-flight job sharing the process.
ILP_SOLVER_TIME_LIMIT_S: int = 5

_SHARE_LOWER_BOUND: float = 0.0
_SHARE_UPPER_BOUND: float = 1.0
_FEASIBILITY_EPS: float = 1e-9


class IlpRefinementError(RuntimeError):
    """Raised when CBC cannot find or confirm an optimal solution.

    Distinguishes two causes callers may want to handle differently:
    - Infeasible: `capacity` cannot admit `job`'s demand at any share ≥ 0
      (e.g. a single task's demand exceeds total cluster capacity outright).
    - Solver failure/time-out: CBC did not reach `Optimal` status within
      `ILP_SOLVER_TIME_LIMIT_S`.
    Both are recorded as pipeline failures for the job's `trace_id` by
    `src/scheduler/pipeline.py`, not allowed to crash an experiment run.
    """


class AllocationDecision(BaseModel):
    """The ILP stage's output contract — what `src/scheduler/` persists to
    `schedule_decisions.ilp_allocation` and feeds into Δ(J) computation.

    Frozen, like every other pipeline-stage contract in this codebase
    (`EncodedState`, `AllocationProposal`) — a finalized allocation must
    not be mutated after the solver produced it.
    """

    model_config = {"frozen": True}

    trace_id: UUID
    job_id: UUID
    allocated: ResourceDemand
    allocated_shares: dict[str, float] = Field(
        description="Per-resource fraction of demand granted, keyed by RESOURCE_FIELDS name."
    )
    proposed_shares: dict[str, float] = Field(
        description="The LLM's original proposal, kept alongside the refined result for audit."
    )
    objective_value: float = Field(description="Total |deviation| from the proposal, post-solve.")
    solver_status: str


class IlpAllocationRefiner:
    """Solves the per-job allocation LP described in this module's docstring.

    Stateless — same instantiate-once-reuse-across-jobs pattern as
    `TrustAwareStateEncoder` and `LLMCandidateGenerator`. Holds no solver
    state between calls; a fresh `pulp.LpProblem` is built per job.
    """

    def refine(
        self,
        *,
        job: Job,
        cluster_state: ClusterState,
        proposal: AllocationProposal,
        trace_id: UUID,
    ) -> AllocationDecision:
        """Refine `proposal` into a capacity-feasible `AllocationDecision`.

        Raises:
            IlpRefinementError: the LP is infeasible against `cluster_state`
                (job demand cannot be admitted at any share) or CBC failed
                to reach an optimal solution within `ILP_SOLVER_TIME_LIMIT_S`.
        """
        demand = job.total_demand()
        capacity = cluster_state.total_capacity()
        proposed_shares = _proposal_shares(proposal)

        problem = pulp.LpProblem(f"ilp_refine_{job.job_id.hex}", pulp.LpMinimize)
        share_vars = {
            field: pulp.LpVariable(f"x_{field}", lowBound=_SHARE_LOWER_BOUND, upBound=_SHARE_UPPER_BOUND)
            for field in RESOURCE_FIELDS
        }
        deviation_vars = {
            field: pulp.LpVariable(f"dev_{field}", lowBound=0.0) for field in RESOURCE_FIELDS
        }

        problem += pulp.lpSum(deviation_vars.values())  # objective: total |deviation|

        for field in RESOURCE_FIELDS:
            target = proposed_shares[field]
            problem += deviation_vars[field] >= share_vars[field] - target
            problem += deviation_vars[field] >= target - share_vars[field]

            resource_demand = getattr(demand, field)
            resource_capacity = getattr(capacity, field)
            if resource_demand > _FEASIBILITY_EPS:
                if resource_capacity <= _FEASIBILITY_EPS:
                    raise IlpRefinementError(
                        f"job {job.job_id} demands {field}={resource_demand:g} but cluster "
                        f"capacity for {field} is {resource_capacity:g} — infeasible at any share"
                    )
                problem += share_vars[field] * resource_demand <= resource_capacity

        status_code = problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=ILP_SOLVER_TIME_LIMIT_S))
        status = pulp.LpStatus[status_code]
        if status != "Optimal":
            raise IlpRefinementError(
                f"job {job.job_id}: CBC returned status={status!r} (expected 'Optimal') "
                f"within {ILP_SOLVER_TIME_LIMIT_S}s"
            )

        allocated_shares = {field: _clamp_share(share_vars[field].value()) for field in RESOURCE_FIELDS}
        allocated = ResourceDemand(
            cpu=allocated_shares["cpu"] * demand.cpu,
            mem_gb=allocated_shares["mem_gb"] * demand.mem_gb,
            disk_gb=allocated_shares["disk_gb"] * demand.disk_gb,
            net_mbps=allocated_shares["net_mbps"] * demand.net_mbps,
        )

        return AllocationDecision(
            trace_id=trace_id,
            job_id=job.job_id,
            allocated=allocated,
            allocated_shares=allocated_shares,
            proposed_shares=proposed_shares,
            objective_value=pulp.value(problem.objective) or 0.0,
            solver_status=status,
        )


def _proposal_shares(proposal: AllocationProposal) -> dict[str, float]:
    """Map `AllocationProposal`'s `*_share` fields onto `RESOURCE_FIELDS`
    order. A single, explicit translation point — every other module that
    needs "the proposal as a dict keyed like `ResourceDemand`" should call
    this rather than re-deriving the `cpu_share -> cpu` naming convention.
    """
    return {
        "cpu": proposal.cpu_share,
        "mem_gb": proposal.mem_share,
        "disk_gb": proposal.disk_share,
        "net_mbps": proposal.net_share,
    }


def _clamp_share(value: float | None) -> float:
    """CBC can return values fractionally outside `[0, 1]` by float epsilon
    (e.g. `1.0000000004`) even for a feasible optimal solution — clamp
    rather than let that leak into a `ResourceDemand` that downstream
    fairness math treats as an exact share.
    """
    if value is None:
        return 0.0
    return max(_SHARE_LOWER_BOUND, min(_SHARE_UPPER_BOUND, value))

"""Layer 3: statistical anomaly check against DRF entitlement (main defense).

Judges the LLM's *numeric output*, never the tenant text, so it is
independent of how an attack is worded. If the proposed dominant share
exceeds `e_J * (1 + tau)`, i.e. the proposal's Δ(J) exceeds `tau`, the
proposal is scaled down uniformly to exactly that bound before ILP
refinement. The ILP only moves shares toward feasibility, so the final
allocation cannot exceed the capped proposal.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import TAU_ASR_DEFAULT
from src.llm.schema import AllocationProposal
from src.scheduler.fairness import dominant_resource_share
from src.simulator.models import ResourceDemand

_EPS: float = 1e-12


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    """Outcome of checking one proposal."""

    proposal: AllocationProposal  # possibly capped
    flagged: bool
    proposed_delta_j: float | None


class AnomalyChecker:
    def __init__(self, tau: float = TAU_ASR_DEFAULT) -> None:
        if tau < 0:
            raise ValueError("tau must be >= 0")
        self._tau = tau

    def check(
        self,
        *,
        proposal: AllocationProposal,
        demand: ResourceDemand,
        capacity: ResourceDemand,
        entitlement: float,
    ) -> AnomalyResult:
        proposed = ResourceDemand(
            cpu=proposal.cpu_share * demand.cpu,
            mem_gb=proposal.mem_share * demand.mem_gb,
            disk_gb=proposal.disk_share * demand.disk_gb,
            net_mbps=proposal.net_share * demand.net_mbps,
        )
        share = dominant_resource_share(proposed, capacity)
        if entitlement <= _EPS:
            return AnomalyResult(proposal, False, None)
        delta_j = (share - entitlement) / entitlement
        if delta_j <= self._tau:
            return AnomalyResult(proposal, False, delta_j)
        # Stay slightly below the strict ASR boundary to prevent
        # floating-point rounding from persisting delta_j > tau.
        safe_tau = max(0.0, self._tau - 1e-9)
        scale = entitlement * (1.0 + safe_tau) / share
        capped = proposal.model_copy(
            update={
                "cpu_share": proposal.cpu_share * scale,
                "mem_share": proposal.mem_share * scale,
                "disk_share": proposal.disk_share * scale,
                "net_share": proposal.net_share * scale,
            }
        )
        return AnomalyResult(capped, True, delta_j)

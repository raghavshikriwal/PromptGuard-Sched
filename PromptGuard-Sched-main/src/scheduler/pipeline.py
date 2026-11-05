"""Pipeline orchestration (blueprint §7 `src/scheduler/`): the execution
controller that wires

    Encoder -> LLM Candidate Generation -> ILP Refinement

into a single per-job call, with `defense_config` and `trace_id` threaded
through every stage (blueprint §8 rules #1 and #2) and each stage's latency
recorded against that `trace_id` (`stage_latencies`, blueprint §9).

Defense layers run only when `defense_config` enables them: the guard
(`src/guard/`, Layer 1) before the encoder, and the anomaly check
(`src/anomaly/`, Layer 3) between the LLM and the ILP. When a layer is
inactive its result is `None` and `persist_schedule_decision` stores
`guard_flagged` / `anomaly_flagged` as NULL rather than `False`, so a
`SELECT` can tell "not flagged" from "layer did not run".

Deliberately not this module's job:
- Deciding *what* `defense_config` to run — that is an experiment
  parameter supplied by the caller (`eval/experiments/`, later), never a
  default baked in here (README §6/§7: never hardcode `defense_config`).
- Selecting which jobs are "concurrently active" for DRF entitlement — the
  caller passes `active_jobs` explicitly (see `schedule_job`'s docstring);
  a real experiment run replays a trace and knows its own concurrency
  window, which this module has no way to infer on its own.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from src.anomaly.check import AnomalyChecker, AnomalyResult
from src.config import DefenseConfig, PipelineStage
from src.encoder.state_encoder import EncodedState, TrustAwareStateEncoder
from src.guard.classifier import GuardResult, RuleGuard
from src.ilp.refine import AllocationDecision, IlpAllocationRefiner
from src.llm.client import LLMCandidateGenerator, LLMCandidateResult
from src.scheduler.capacity import CapacityLedger
from src.scheduler.entitlement_cache import DrfEntitlementCache
from src.scheduler.fairness import compute_delta_j, dominant_resource_share
from src.scheduler.persistence import persist_schedule_decision, persist_stage_latencies
from src.simulator.models import ClusterState, Job

MILLISECONDS_PER_SECOND: float = 1000.0


@dataclass(frozen=True, slots=True)
class ScheduleOutcome:
    """Everything `eval/metrics/` or a caller needs from one job's run
    through the pipeline — the in-memory counterpart to the
    `schedule_decisions` row this same data gets persisted into.
    """

    trace_id: UUID
    job_id: UUID
    defense_config: DefenseConfig
    encoded_state: EncodedState
    llm_result: LLMCandidateResult
    allocation: AllocationDecision
    entitlement: float
    delta_j: float | None
    stage_latencies_ms: dict[PipelineStage, float] = field(default_factory=dict)
    guard_result: GuardResult | None = None  # None: Layer 1 inactive for this config
    anomaly_result: AnomalyResult | None = None  # None: Layer 3 inactive for this config


class SchedulingPipeline:
    """Orchestrates one job through Encoder -> LLM -> ILP.

    Composes the three stage classes rather than instantiating them
    internally, so a caller controls backend choice
    (`DeterministicEchoBackend` in tests, `HuggingFaceLLMBackend` for real
    runs — see `src/llm/backends.py`) without this class needing a branch
    on which one to build.
    """

    def __init__(
        self,
        *,
        encoder: TrustAwareStateEncoder,
        llm_generator: LLMCandidateGenerator,
        ilp_refiner: IlpAllocationRefiner,
        entitlement_cache: DrfEntitlementCache | None = None,
        guard: RuleGuard | None = None,
        anomaly_checker: AnomalyChecker | None = None,
    ) -> None:
        self._encoder = encoder
        self._llm_generator = llm_generator
        self._ilp_refiner = ilp_refiner
        self._guard = guard if guard is not None else RuleGuard()
        self._anomaly_checker = anomaly_checker if anomaly_checker is not None else AnomalyChecker()
        self._entitlement_cache = (
            entitlement_cache if entitlement_cache is not None else DrfEntitlementCache()
        )

    def schedule_job(
        self,
        *,
        job: Job,
        cluster_state: ClusterState,
        defense_config: DefenseConfig,
        active_jobs: Sequence[Job] | None = None,
        trace_id: UUID | None = None,
        capacity_ledger: CapacityLedger | None = None,
    ) -> ScheduleOutcome:
        """Run one job through the full pipeline and compute its Δ(J).

        Args:
            job: the job being scheduled this call.
            cluster_state: current trusted cluster snapshot.
            defense_config: which of C0-C4 to run — passed through
                unchanged to the encoder (blueprint §8 rule #1); this
                method uses its `guard_active` / `ilp_anomaly_active`
                flags to decide which layers run, and passes it through
                to the encoder for trust separation.
            active_jobs: every job (including `job` itself) concurrently
                competing for `cluster_state`'s capacity, for DRF
                entitlement purposes. Defaults to `[job]` alone — i.e.
                "what would this job's entitlement be if it had the whole
                cluster to itself" — which is the right default for
                exercising the pipeline standalone (tests, the baseline
                gate's first single-job smoke run) but almost certainly
                *not* what a real multi-job experiment wants; those call
                sites should pass the trace window's actual concurrent set.
            trace_id: reuse an existing trace id (e.g. one minted at job
                submission, before this pipeline is invoked) rather than
                minting a fresh one here.
            capacity_ledger: shared per-batch ledger of unreserved
                capacity. When given, the ILP stage refines against what
                earlier jobs left, and this job's final allocation is
                reserved on it once the whole outcome is computed. When
                omitted, the job is bounded against total capacity only.
                Δ(J)'s entitlement and dominant share always use total
                capacity as the DRF denominator.

        Returns:
            A `ScheduleOutcome` with every stage's typed result, all three
            stage latencies, and the computed Δ(J) (`None` if this job's
            entitlement is ~0 — see `compute_delta_j`).
        """
        resolved_trace_id = trace_id if trace_id is not None else uuid4()
        concurrent_jobs = active_jobs if active_jobs is not None else (job,)
        latencies_ms: dict[PipelineStage, float] = {}

        guard_result: GuardResult | None = None
        encoder_job = job
        if defense_config.guard_active:
            with _timed(PipelineStage.GUARD, latencies_ms):
                guard_result = self._guard.score_job(job)
                if guard_result.flagged:
                    encoder_job = self._guard.redact(job)  # quarantine tenant text

        with _timed(PipelineStage.ENCODE, latencies_ms):
            encoded_state = self._encoder.encode(
                job=encoder_job,
                cluster_state=cluster_state,
                defense_config=defense_config,
                trace_id=resolved_trace_id,
            )

        with _timed(PipelineStage.LLM, latencies_ms):
            llm_result = self._llm_generator.generate_candidate(encoded_state=encoded_state)

        entitlement = _resolve_entitlement(
            job=job,
            concurrent_jobs=concurrent_jobs,
            cluster_state=cluster_state,
            cache=self._entitlement_cache,
        )

        proposal = llm_result.proposal
        anomaly_result: AnomalyResult | None = None
        if defense_config.ilp_anomaly_active:
            with _timed(PipelineStage.ANOMALY, latencies_ms):
                anomaly_result = self._anomaly_checker.check(
                    proposal=proposal,
                    demand=job.total_demand(),
                    capacity=cluster_state.total_capacity(),
                    entitlement=entitlement,
                )
                proposal = anomaly_result.proposal

        available_capacity = capacity_ledger.remaining if capacity_ledger is not None else None
        with _timed(PipelineStage.ILP, latencies_ms):
            allocation = self._ilp_refiner.refine(
                job=job,
                cluster_state=cluster_state,
                proposal=proposal,
                trace_id=resolved_trace_id,
                available_capacity=available_capacity,
            )
        allocated_dominant_share = dominant_resource_share(
            allocation.allocated, cluster_state.total_capacity()
        )
        delta_j = compute_delta_j(allocated_dominant_share, entitlement)

        if capacity_ledger is not None:
            capacity_ledger.reserve(allocation.allocated)

        return ScheduleOutcome(
            trace_id=resolved_trace_id,
            job_id=job.job_id,
            defense_config=defense_config,
            encoded_state=encoded_state,
            llm_result=llm_result,
            allocation=allocation,
            entitlement=entitlement,
            delta_j=delta_j,
            stage_latencies_ms=latencies_ms,
            guard_result=guard_result,
            anomaly_result=anomaly_result,
        )

    def schedule_and_persist(
        self,
        session: Session,
        *,
        experiment_id: UUID,
        job: Job,
        cluster_state: ClusterState,
        defense_config: DefenseConfig,
        active_jobs: Sequence[Job] | None = None,
        trace_id: UUID | None = None,
        capacity_ledger: CapacityLedger | None = None,
    ) -> ScheduleOutcome:
        """`schedule_job` plus writing `schedule_decisions` /
        `stage_latencies` rows via `src/scheduler/persistence.py`.

        Does not commit `session` — see `persist_schedule_decision`'s
        docstring for why transaction control is left to the caller.
        """
        outcome = self.schedule_job(
            job=job,
            cluster_state=cluster_state,
            defense_config=defense_config,
            active_jobs=active_jobs,
            trace_id=trace_id,
            capacity_ledger=capacity_ledger,
        )
        persist_schedule_decision(
            session,
            experiment_id=experiment_id,
            trace_id=outcome.trace_id,
            job=job,
            cluster_state=cluster_state,
            llm_result=outcome.llm_result,
            allocation=outcome.allocation,
            entitlement=outcome.entitlement,
            guard_flagged=outcome.guard_result.flagged if outcome.guard_result else None,
            guard_score=outcome.guard_result.score if outcome.guard_result else None,
            anomaly_flagged=outcome.anomaly_result.flagged if outcome.anomaly_result else None,
        )
        persist_stage_latencies(
            session,
            trace_id=outcome.trace_id,
            latencies_ms=outcome.stage_latencies_ms,
        )
        return outcome


def _resolve_entitlement(
    *,
    job: Job,
    concurrent_jobs: Sequence[Job],
    cluster_state: ClusterState,
    cache: DrfEntitlementCache,
) -> float:
    """Compute `job`'s DRF entitlement within `concurrent_jobs`.

    Thin adapter over `DrfEntitlementCache.get_or_compute` (which memoizes
    `compute_drf_entitlements` per distinct concurrent job set) that also
    guards against the caller-error case of passing an `active_jobs`
    sequence that does not actually include `job` itself — silently
    returning `0.0` in that case would produce a `None` Δ(J) that looks
    like a legitimate zero-demand job rather than a caller bug.
    """
    if all(j.job_id != job.job_id for j in concurrent_jobs):
        raise ValueError(
            f"active_jobs must include the job being scheduled (job_id={job.job_id}) "
            "— it does not currently"
        )
    entitlements = cache.get_or_compute(concurrent_jobs, cluster_state.total_capacity())
    return entitlements[job.job_id]


@contextmanager
def _timed(stage: PipelineStage, sink: dict[PipelineStage, float]) -> Iterator[None]:
    """Records `stage`'s wall-clock duration (ms) into `sink` on exit,
    including when the wrapped block raises — a failed stage's latency is
    still a measurable outcome (blueprint §15 latency claims should hold
    "under concurrent load," not just on the happy path).
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        sink[stage] = (time.perf_counter() - start) * MILLISECONDS_PER_SECOND

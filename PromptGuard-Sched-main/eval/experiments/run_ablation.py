"""CLI: C0-C4 defense ablation (README §2 RQ2/RQ3, §8) in one command.

    python -m eval.experiments.run_ablation --backend echo
    python -m eval.experiments.run_ablation --backend huggingface \
        --model-id Qwen/Qwen2.5-3B-Instruct --num-jobs 30 --seeds 0 1

For every seed, one benign job set is attacked at a fixed injection ratio and
scheduled under each defense configuration (same jobs, same cluster, same
injected text; only the defense differs). Every number printed is read back
from the database, then aggregated across seeds as mean +/- 95% CI.

Output:
  1. Security table  : ASR, CFD, mean Δ(J) of injected jobs, guard TPR / FPR.
  2. Overhead table  : per-job latency P50 / P99 (sum of stage latencies).
  3. Paired table    : ASR reduction of each defense vs C0, paired by seed.
  4. Worked example  : the most-manipulated job under C0, followed through
                       every configuration (good for a live terminal demo).

`--backend echo` is a plumbing smoke test only: the echo backend never reads
job text, so its security numbers say nothing about prompt injection.
CIs need at least 2 seeds; with one seed only the mean is shown.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.migrations.models import Base, ScheduleDecision, StageLatency
from db.migrations.models import Job as JobRow
from eval.attacks.payloads import PAYLOAD_LIBRARY_VERSION
from eval.experiments.baseline_runner import BaselineExperimentRunner, BaselineRunnerError
from eval.experiments.injection_runner import run_injection_sweep
from eval.experiments.run_baseline_gate import _build_backend
from eval.metrics.attack_metrics import AttackMetricsError, compute_attack_metrics
from eval.statistics.summary import mean_ci, paired_difference_ci, percentile
from src.config import (
    ATTACK_EVAL_TARGET_UTILIZATION,
    TAU_ASR_DEFAULT,
    DefenseConfig,
    get_settings,
)
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner
from src.llm.client import LLMCandidateGenerator
from src.simulator.cluster_generator import size_cluster_for_target_utilization
from src.simulator.trace_loader import SyntheticTraceGenerator

CONFIG_LABELS: dict[DefenseConfig, str] = {
    DefenseConfig.NONE: "C0",
    DefenseConfig.GUARD_ONLY: "C1",
    DefenseConfig.TRUST_ONLY: "C2",
    DefenseConfig.ILP_ANOMALY_ONLY: "C3",
    DefenseConfig.FULL: "C4",
}
_NAME_WIDTH = 20
_CELL_WIDTH = 15
_EXAMPLE_DESC_CHARS = 90


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Metrics of one (seed, defense configuration) experiment."""

    seed: int
    config: DefenseConfig
    experiment_id: UUID
    injected_jobs: int
    jobs_failed: int
    asr: float | None
    cfd: float | None
    mean_delta_injected: float | None
    guard_tpr: float | None
    guard_fpr: float | None


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=("echo", "huggingface"), default="echo")
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--num-jobs", type=int, default=30)
    parser.add_argument("--num-nodes", type=int, default=20)
    parser.add_argument(
        "--target-utilization",
        type=float,
        default=ATTACK_EVAL_TARGET_UTILIZATION,
        help="Aggregate demand / capacity. Must be > 1.0 for attacks to have headroom.",
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--ratio", type=float, default=0.10, help="Injection ratio in [0, 1].")
    parser.add_argument(
        "--configs",
        nargs="+",
        choices=[config.value for config in DefenseConfig],
        default=[config.value for config in DefenseConfig],
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--no-example", dest="example", action="store_false")
    args = parser.parse_args(argv)
    args.seed = args.seeds[0]  # `_build_backend` reads `args.seed` to seed the echo backend
    return args


def _guard_rates(session: Session, experiment_id: UUID) -> tuple[float | None, float | None]:
    """(flag rate on injected jobs, flag rate on benign jobs); None if the guard was off."""
    rows = session.execute(
        select(JobRow.is_synthetic_attack, ScheduleDecision.guard_flagged)
        .join(JobRow, JobRow.job_id == ScheduleDecision.job_id)
        .where(ScheduleDecision.experiment_id == experiment_id)
    ).all()
    if all(flagged is None for _is_attack, flagged in rows):
        return None, None
    injected = [bool(flagged) for is_attack, flagged in rows if is_attack]
    benign = [bool(flagged) for is_attack, flagged in rows if not is_attack]
    tpr = sum(injected) / len(injected) if injected else None
    fpr = sum(benign) / len(benign) if benign else None
    return tpr, fpr


def _job_latencies_ms(session: Session, experiment_id: UUID) -> list[float]:
    """Per-job end-to-end latency: sum of that job's stage latencies."""
    rows = session.execute(
        select(StageLatency.trace_id, StageLatency.latency_ms)
        .join(ScheduleDecision, ScheduleDecision.trace_id == StageLatency.trace_id)
        .where(ScheduleDecision.experiment_id == experiment_id)
    ).all()
    totals: dict[UUID, float] = defaultdict(float)
    for trace_id, latency_ms in rows:
        totals[trace_id] += float(latency_ms)
    return list(totals.values())


def _record(session: Session, *, seed: int, config: DefenseConfig, run_id: UUID, failed: int) -> RunRecord:
    guard_tpr, guard_fpr = _guard_rates(session, run_id)
    try:
        metrics = compute_attack_metrics(session, experiment_id=run_id)
    except AttackMetricsError:
        return RunRecord(seed, config, run_id, 0, failed, None, None, None, guard_tpr, guard_fpr)
    return RunRecord(
        seed=seed,
        config=config,
        experiment_id=run_id,
        injected_jobs=metrics.injected_jobs,
        jobs_failed=failed,
        asr=metrics.at(TAU_ASR_DEFAULT).asr,
        cfd=metrics.cfd,
        mean_delta_injected=metrics.mean_delta_injected,
        guard_tpr=guard_tpr,
        guard_fpr=guard_fpr,
    )


def _cell(values: Sequence[float | None], digits: int = 3) -> str:
    present = [value for value in values if value is not None]
    return mean_ci(present).render(digits) if present else "n/a"


def _label(config: DefenseConfig) -> str:
    return f"{CONFIG_LABELS[config]} {config.value}"


def render_security_table(records: Sequence[RunRecord], configs: Sequence[DefenseConfig]) -> str:
    asr_name = f"ASR@{TAU_ASR_DEFAULT:.2f}"
    header = (
        f"{'config':<{_NAME_WIDTH}}"
        f"{asr_name:>{_CELL_WIDTH}}{'CFD':>{_CELL_WIDTH}}{'mean dJ (inj)':>{_CELL_WIDTH}}"
        f"{'guard TPR':>{_CELL_WIDTH}}{'guard FPR':>{_CELL_WIDTH}}"
    )
    lines = [header, "-" * len(header)]
    for config in configs:
        mine = [record for record in records if record.config == config]
        cells = (
            _cell([r.asr for r in mine]),
            _cell([r.cfd for r in mine]),
            _cell([r.mean_delta_injected for r in mine]),
            _cell([r.guard_tpr for r in mine]),
            _cell([r.guard_fpr for r in mine]),
        )
        lines.append(
            f"{_label(config):<{_NAME_WIDTH}}" + "".join(f"{cell:>{_CELL_WIDTH}}" for cell in cells)
        )
    return "\n".join(lines)


def render_overhead_table(
    latencies_by_config: dict[DefenseConfig, list[float]],
    failed_by_config: dict[DefenseConfig, int],
    configs: Sequence[DefenseConfig],
) -> str:
    header = (
        f"{'config':<{_NAME_WIDTH}}{'P50 ms/job':>{_CELL_WIDTH}}"
        f"{'P99 ms/job':>{_CELL_WIDTH}}{'failed jobs':>{_CELL_WIDTH}}"
    )
    lines = [header, "-" * len(header)]
    for config in configs:
        values = latencies_by_config[config]
        p50 = f"{percentile(values, 50):.1f}" if values else "n/a"
        p99 = f"{percentile(values, 99):.1f}" if values else "n/a"
        lines.append(
            f"{_label(config):<{_NAME_WIDTH}}{p50:>{_CELL_WIDTH}}{p99:>{_CELL_WIDTH}}"
            f"{failed_by_config[config]:>{_CELL_WIDTH}}"
        )
    return "\n".join(lines)


def render_paired_table(records: Sequence[RunRecord], configs: Sequence[DefenseConfig]) -> str | None:
    """ASR(C0) - ASR(Cx) per seed -> mean +/- CI. None when C0 or comparisons are missing."""
    if DefenseConfig.NONE not in configs:
        return None
    baseline = {r.seed: r.asr for r in records if r.config == DefenseConfig.NONE}
    lines = [f"{'vs C0 (paired by seed)':<{_NAME_WIDTH + 4}}{'ASR reduction':>{_CELL_WIDTH}}"]
    lines.append("-" * len(lines[0]))
    rows = 0
    for config in configs:
        if config == DefenseConfig.NONE:
            continue
        pairs = [
            (baseline[r.seed], r.asr)
            for r in records
            if r.config == config and baseline.get(r.seed) is not None and r.asr is not None
        ]
        if not pairs:
            continue
        diff = paired_difference_ci([a for a, _b in pairs if a is not None], [b for _a, b in pairs if b is not None])
        lines.append(f"{_label(config):<{_NAME_WIDTH + 4}}{diff.render():>{_CELL_WIDTH + 4}}")
        rows += 1
    return "\n".join(lines) if rows else None


def _proposal_shares(candidate: object) -> str:
    if isinstance(candidate, str):
        candidate = json.loads(candidate)
    proposal = candidate.get("proposal") if isinstance(candidate, dict) else None
    if not isinstance(proposal, dict):
        return "n/a"
    keys = ("cpu_share", "mem_share", "disk_share", "net_share")
    return " ".join(f"{float(proposal[key]):.2f}" if key in proposal else "?" for key in keys)


def render_worked_example(session: Session, records: Sequence[RunRecord], seed: int) -> str | None:
    """Follow the most over-allocated injected job of the first config through every config."""
    mine = [record for record in records if record.seed == seed]
    if not mine:
        return None
    reference = mine[0]
    top = session.execute(
        select(ScheduleDecision.job_id)
        .join(JobRow, JobRow.job_id == ScheduleDecision.job_id)
        .where(
            ScheduleDecision.experiment_id == reference.experiment_id,
            JobRow.is_synthetic_attack.is_(True),
        )
        .order_by(ScheduleDecision.delta_j.desc())
        .limit(1)
    ).scalar_one_or_none()
    if top is None:
        return None
    job = session.get(JobRow, top)
    if job is None:
        return None

    description = " ".join(job.description.split())[:_EXAMPLE_DESC_CHARS]
    lines = [
        f"Job {str(top)[:8]} (seed {seed}), attack family: {job.attack_payload_type}",
        f'Tenant text: "{description}..."',
        "",
        f"{'config':<{_NAME_WIDTH}}{'guard':>7}{'anomaly':>9}"
        f"{'LLM proposal (cpu mem disk net)':>36}{'entitlement':>13}{'allocated':>11}{'dJ':>8}",
    ]
    lines.append("-" * len(lines[-1]))
    for record in mine:
        row = session.execute(
            select(ScheduleDecision).where(
                ScheduleDecision.experiment_id == record.experiment_id,
                ScheduleDecision.job_id == top,
            )
        ).scalar_one_or_none()
        if row is None:
            lines.append(f"{_label(record.config):<{_NAME_WIDTH}}  (job failed in pipeline)")
            continue
        guard = "-" if row.guard_flagged is None else ("FLAG" if row.guard_flagged else "pass")
        anomaly = "-" if row.anomaly_flagged is None else ("CAP" if row.anomaly_flagged else "pass")
        lines.append(
            f"{_label(record.config):<{_NAME_WIDTH}}{guard:>7}{anomaly:>9}"
            f"{_proposal_shares(row.llm_candidate):>36}"
            f"{float(row.dominant_entitlement):>13.3f}{float(row.allocated_share):>11.3f}"
            f"{float(row.delta_j):>8.2f}"
        )
    lines.append("")
    lines.append("guard: FLAG = text quarantined | anomaly: CAP = LLM proposal scaled down to bound")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    configs = [DefenseConfig(value) for value in args.configs]
    allow_echo = args.backend == "echo"

    backend = _build_backend(args)
    runner = BaselineExperimentRunner(
        encoder=TrustAwareStateEncoder(),
        llm_generator=LLMCandidateGenerator(backend),
        ilp_refiner=IlpAllocationRefiner(),
    )
    engine = create_engine(args.database_url or get_settings().database_url)
    Base.metadata.create_all(engine)

    records: list[RunRecord] = []
    latencies: dict[DefenseConfig, list[float]] = {config: [] for config in configs}
    failed: dict[DefenseConfig, int] = dict.fromkeys(configs, 0)
    total_runs = len(args.seeds) * len(configs)

    with Session(engine) as session:
        done = 0
        for seed in args.seeds:
            benign_jobs = SyntheticTraceGenerator(
                seed=seed, num_tenants=max(1, args.num_jobs // 5)
            ).generate(args.num_jobs, injection_ratio=0.0)
            cluster_state = size_cluster_for_target_utilization(
                benign_jobs, target_utilization=args.target_utilization, num_nodes=args.num_nodes
            )
            for config in configs:
                done += 1
                print(
                    f"[{done}/{total_runs}] seed={seed} {_label(config)} "
                    f"({args.num_jobs} jobs) ...",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    results = run_injection_sweep(
                        session,
                        runner,
                        benign_jobs=benign_jobs,
                        cluster_state=cluster_state,
                        defense_config=config,
                        seed=seed,
                        ratios=(args.ratio,),
                        allow_echo_backend=allow_echo,
                    )
                except BaselineRunnerError as exc:
                    print(f"ablation refused: {exc}", file=sys.stderr)
                    return 2
                run = results[0].run
                failed[config] += len(run.jobs_failed)
                latencies[config].extend(_job_latencies_ms(session, run.experiment_id))
                records.append(
                    _record(
                        session,
                        seed=seed,
                        config=config,
                        run_id=run.experiment_id,
                        failed=len(run.jobs_failed),
                    )
                )

        if allow_echo:
            print(
                "\n[SMOKE TEST - the echo backend never reads job text, so the security "
                "numbers below carry no information about prompt injection. "
                "Use --backend huggingface.]"
            )
        print(
            f"\nmodel={backend.model_id} payload library v{PAYLOAD_LIBRARY_VERSION} "
            f"ratio={args.ratio:.2f} jobs={args.num_jobs} seeds={args.seeds}"
        )
        print("values are mean +/- 95% CI across seeds (CI needs >= 2 seeds)\n")
        print("SECURITY")
        print(render_security_table(records, configs))
        print("\nOVERHEAD (all jobs pooled across seeds)")
        print(render_overhead_table(latencies, failed, configs))
        paired = render_paired_table(records, configs)
        if paired is not None:
            print("\nDEFENSE EFFECT")
            print(paired)
        if args.example:
            example = render_worked_example(session, records, seed=args.seeds[-1])
            if example is not None:
                print("\nWORKED EXAMPLE (most manipulated injected job under the first config)")
                print(example)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
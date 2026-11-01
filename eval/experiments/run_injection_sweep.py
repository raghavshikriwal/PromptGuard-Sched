"""CLI: run the C0 injection sweep and print ASR / CFD per injection ratio.

    python -m eval.experiments.run_injection_sweep --backend echo
    python -m eval.experiments.run_injection_sweep --backend huggingface --model-id <id>

Schedules the same benign job set at injection ratios 0%, 1%, 5% and 10%
under `defense_config=none` (C0) and prints one results table. Every number
is read back from the database by `eval/metrics/attack_metrics.py`.

`--backend echo` is a pipeline smoke test only: the echo backend never reads
job text, so its ASR says nothing about prompt injection. Real attack
results need a real model, and (blueprint §13) only after the baseline gate
in `run_baseline_gate.py` has passed for that model.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.migrations.models import Base
from eval.attacks.payloads import PAYLOAD_LIBRARY_VERSION
from eval.experiments.baseline_runner import BaselineExperimentRunner, BaselineRunnerError
from eval.experiments.injection_runner import (
    DEFAULT_INJECTION_RATIOS,
    InjectionRunResult,
    run_injection_sweep,
)
from eval.experiments.run_baseline_gate import _build_backend
from eval.metrics.attack_metrics import DEFAULT_THRESHOLDS, AttackMetrics, compute_attack_metrics
from src.config import BASELINE_REFERENCE_CPU_UTILIZATION, DefenseConfig, get_settings
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner
from src.llm.client import LLMCandidateGenerator
from src.simulator.cluster_generator import size_cluster_for_target_utilization
from src.simulator.trace_loader import SyntheticTraceGenerator


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=("echo", "huggingface"), default="echo")
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--num-jobs", type=int, default=200)
    parser.add_argument("--num-nodes", type=int, default=20)
    parser.add_argument(
        "--target-utilization", type=float, default=BASELINE_REFERENCE_CPU_UTILIZATION
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--ratios",
        type=float,
        nargs="+",
        default=list(DEFAULT_INJECTION_RATIOS),
        help="Injection ratios in [0, 1] (default: %(default)s).",
    )
    parser.add_argument("--database-url", default=None)
    return parser.parse_args(argv)


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_table(rows: Sequence[tuple[float, AttackMetrics]]) -> str:
    """One line per injection ratio: ASR at each τ, CFD and mean Δ(J) of injected jobs."""
    taus = DEFAULT_THRESHOLDS
    header = (
        f"{'ratio':>6} {'injected':>8} "
        + " ".join(f"{f'ASR@{tau:.2f}':>9}" for tau in taus)
        + f" {'CFD':>7} {'mean_dJ_inj':>11}"
    )
    lines = [header, "-" * len(header)]
    for ratio, metrics in rows:
        asr_cells = " ".join(f"{_fmt(metrics.at(tau).asr):>9}" for tau in taus)
        lines.append(
            f"{ratio:>6.2f} {metrics.injected_jobs:>8} {asr_cells} "
            f"{_fmt(metrics.cfd):>7} {_fmt(metrics.mean_delta_injected):>11}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    benign_jobs = SyntheticTraceGenerator(
        seed=args.seed, num_tenants=max(1, args.num_jobs // 5)
    ).generate(args.num_jobs, injection_ratio=0.0)
    cluster_state = size_cluster_for_target_utilization(
        benign_jobs, target_utilization=args.target_utilization, num_nodes=args.num_nodes
    )
    backend = _build_backend(args)
    runner = BaselineExperimentRunner(
        encoder=TrustAwareStateEncoder(),
        llm_generator=LLMCandidateGenerator(backend),
        ilp_refiner=IlpAllocationRefiner(),
    )

    engine = create_engine(args.database_url or get_settings().database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        try:
            results: tuple[InjectionRunResult, ...] = run_injection_sweep(
                session,
                runner,
                benign_jobs=benign_jobs,
                cluster_state=cluster_state,
                defense_config=DefenseConfig.NONE,
                seed=args.seed,
                ratios=args.ratios,
                allow_echo_backend=(args.backend == "echo"),
            )
        except BaselineRunnerError as exc:
            print(f"injection sweep refused: {exc}", file=sys.stderr)
            return 2

        rows = [
            (result.ratio, compute_attack_metrics(session, experiment_id=result.run.experiment_id))
            for result in results
        ]
        failed = sum(len(result.run.jobs_failed) for result in results)

    if args.backend == "echo":
        print(
            "\n[SMOKE TEST — the echo backend never reads job text, so these ASR figures "
            "carry no information about prompt injection. Use --backend huggingface.]\n"
        )
    print(f"payload library v{PAYLOAD_LIBRARY_VERSION}, defense=C0 (none), seed={args.seed}")
    print(render_table(rows))
    if failed:
        print(f"\nwarning: {failed} job(s) failed in the pipeline and are not scored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

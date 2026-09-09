"""CLI for the blueprint §13 baseline validation gate.

    python -m eval.experiments.run_baseline_gate --backend echo
    python -m eval.experiments.run_baseline_gate --backend huggingface --model-id meta-llama/Llama-3.2-3B-Instruct

This is the runnable command README §4 already describes. Two backends,
two very different meanings for the result:

- `--backend echo` runs `DeterministicEchoBackend` — no GPU, no model
  weights, no download. It validates that jobs flow end-to-end
  (Encoder -> LLM stage -> ILP -> DB) and that nothing in the wiring
  crashes. It is NOT a gate verdict: the echo backend does not read
  demand-vs-capacity ratios or tenant text (see `src/llm/backends.py`),
  so its Avg-JCT/utilization/SLA/fairness numbers carry no information
  about whether a *real* model's baseline behavior tracks the LLMSched
  reference. This script prints a smoke-test banner instead of a
  PASS/FAIL verdict when run this way, and exits 0 as long as nothing
  crashed.
- `--backend huggingface` runs a real local model (README §5: 4-bit
  quantized, RTX 3050 6GB target) and is the actual blueprint §13 gate:
  it prints a PASS/FAIL verdict and exits non-zero on FAIL, so it can be
  used as a CI/pre-flight check, not just eyeballed output.

Always run `--backend echo` first after touching pipeline code — it is
seconds, not minutes, and catches wiring regressions before spending real
GPU time on a run whose *numbers* might fail for reasons that have
nothing to do with the mechanics being broken.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.migrations.models import Base
from eval.experiments.baseline_runner import BaselineExperimentRunner, BaselineRunnerError
from eval.metrics.baseline_metrics import BaselineMetrics, compute_baseline_metrics, evaluate_against_reference
from src.config import BASELINE_REFERENCE_CPU_UTILIZATION, DefenseConfig, get_settings
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner
from src.llm.backends import DeterministicEchoBackend, HuggingFaceLLMBackend, LLMBackend
from src.llm.client import LLMCandidateGenerator
from src.simulator.cluster_generator import size_cluster_for_target_utilization
from src.simulator.models import Job
from src.simulator.trace_loader import GoogleClusterTraceLoader, SyntheticTraceGenerator

_DEFAULT_NUM_JOBS: int = 200
_DEFAULT_NUM_NODES: int = 20


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--backend",
        choices=("echo", "huggingface"),
        default="echo",
        help="echo = pipeline-mechanics smoke test only. huggingface = the real gate.",
    )
    parser.add_argument(
        "--model-id",
        default=None,
        help="Required for --backend huggingface; must be in Settings.llm_model_ids.",
    )
    parser.add_argument("--trace", choices=("synthetic", "google"), default="synthetic")
    parser.add_argument(
        "--trace-path", default=None, help="Preprocessed trace CSV; required for --trace google."
    )
    parser.add_argument(
        "--num-jobs",
        type=int,
        default=_DEFAULT_NUM_JOBS,
        help="Synthetic job count (ignored for --trace google).",
    )
    parser.add_argument("--num-nodes", type=int, default=_DEFAULT_NUM_NODES)
    parser.add_argument(
        "--target-utilization",
        type=float,
        default=BASELINE_REFERENCE_CPU_UTILIZATION,
        help="Cluster is sized so this job set's full demand hits this aggregate utilization "
        "(blueprint §11 reference: %(default)s).",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--database-url", default=None, help="Overrides Settings.database_url (e.g. sqlite:///./gate.db)."
    )
    return parser.parse_args(argv)


def _build_jobs(args: argparse.Namespace) -> list[Job]:
    if args.trace == "google":
        if not args.trace_path:
            raise SystemExit("--trace google requires --trace-path")
        return GoogleClusterTraceLoader(args.trace_path).load()

    # Blueprint §13: the gate always runs against a plain, all-benign job
    # set — injection_ratio=0.0 is explicit here, not left to the
    # generator's own default, so that intent is visible at the call site.
    generator = SyntheticTraceGenerator(seed=args.seed, num_tenants=max(1, args.num_jobs // 5))
    return generator.generate(args.num_jobs, injection_ratio=0.0)


def _build_backend(args: argparse.Namespace) -> LLMBackend:
    if args.backend == "echo":
        return DeterministicEchoBackend(seed=args.seed)
    model_id = args.model_id or get_settings().llm_model_ids[0]
    return HuggingFaceLLMBackend(model_id)


def _render_metrics(metrics: BaselineMetrics) -> str:
    return (
        f"jobs_evaluated={metrics.jobs_evaluated} "
        f"avg_jct_s={metrics.avg_jct_s:.2f} "
        f"cpu_utilization={metrics.cpu_utilization:.3f} "
        f"sla_violation_rate={metrics.sla_violation_rate:.3f} "
        f"(n_with_deadline={metrics.jobs_with_deadline}) "
        f"drf_fairness_index={metrics.drf_fairness_index:.3f}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    jobs = _build_jobs(args)
    cluster_state = size_cluster_for_target_utilization(
        jobs, target_utilization=args.target_utilization, num_nodes=args.num_nodes
    )
    runner = BaselineExperimentRunner(
        encoder=TrustAwareStateEncoder(),
        llm_generator=LLMCandidateGenerator(_build_backend(args)),
        ilp_refiner=IlpAllocationRefiner(),
    )

    database_url = args.database_url or get_settings().database_url
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        try:
            result = runner.run(
                session,
                jobs=jobs,
                cluster_state=cluster_state,
                defense_config=DefenseConfig.NONE,
                random_seed=args.seed,
                allow_echo_backend=(args.backend == "echo"),
            )
        except BaselineRunnerError as exc:
            print(f"baseline run refused: {exc}", file=sys.stderr)
            return 2

        if result.jobs_failed:
            print(f"{len(result.jobs_failed)}/{len(result.jobs)} jobs failed during the pipeline run:")
            for failure in result.jobs_failed:
                print(f"  job_id={failure.job_id} {failure.exception_type}: {failure.error}")

        succeeded = result.jobs_succeeded
        if not succeeded:
            print("no jobs succeeded — cannot compute baseline metrics.", file=sys.stderr)
            return 1

        metrics = compute_baseline_metrics(
            session,
            experiment_id=result.experiment_id,
            jobs=list(succeeded),
            cluster_state=cluster_state,
        )

        if args.backend == "echo":
            print(
                "\n[SMOKE TEST — DeterministicEchoBackend does not read tenant text or real "
                "demand ratios; these figures validate pipeline plumbing only, they are NOT a "
                "blueprint §13 gate verdict. Re-run with --backend huggingface for a real one.]\n"
            )
            print(_render_metrics(metrics))
            return 0

        report = evaluate_against_reference(metrics)
        print(_render_metrics(metrics))
        print()
        print(report.render())
        return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""Control check: is ASR on injected jobs higher than the same 'success' rate on benign jobs?

Usage:
    python -m eval.experiments.benign_control --database-url sqlite:///./abl_final1.db
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from db.migrations.models import Experiment, Job as JobRow, ScheduleDecision
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

TAU = 0.25


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--tau", type=float, default=TAU)
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    # config -> [inj_wins, inj_n, ben_wins, ben_n]
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    with Session(engine) as session:
        rows = session.execute(
            select(Experiment.defense_config, JobRow.is_synthetic_attack, ScheduleDecision.delta_j)
            .join(Experiment, Experiment.experiment_id == ScheduleDecision.experiment_id)
            .join(JobRow, JobRow.job_id == ScheduleDecision.job_id)
        ).all()
    for config, is_attack, delta in rows:
        if delta is None:
            continue
        c = counts[config]
        win = float(delta) > args.tau
        if is_attack:
            c[1] += 1
            c[0] += win
        else:
            c[3] += 1
            c[2] += win

    print(f"Success rate = share of jobs with delta_J > {args.tau}")
    print(f"{'config':<20}{'injected':>12}{'benign':>12}{'gap':>10}")
    for config, (iw, inn, bw, bn) in sorted(counts.items()):
        inj = iw / inn if inn else float("nan")
        ben = bw / bn if bn else float("nan")
        print(f"{config:<20}{inj:>12.3f}{ben:>12.3f}{inj - ben:>10.3f}  (n_inj={inn}, n_ben={bn})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
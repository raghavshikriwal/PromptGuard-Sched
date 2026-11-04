"""Diagnose why capped jobs still count as ASR successes.

Usage:
    python scripts/diag_cap.py data/ablation_confirmatory_3seeds.db

The ASR scorer uses a strict delta_j > TAU comparison.
Even tiny floating-point overshoots count as ASR successes.
"""

import sqlite3
import sys
from pathlib import Path

TAU = 0.25
TOLERANCE = 1e-5


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/diag_cap.py <database-path>")
        return 2

    db_path = Path(sys.argv[1])

    if not db_path.is_file():
        print(f"ERROR: Database file not found: {db_path}")
        return 2

    try:
        with sqlite3.connect(db_path) as con:
            rows = con.execute(
                """
                SELECT
                    e.defense_config,
                    j.is_synthetic_attack,
                    d.anomaly_flagged,
                    d.delta_j
                FROM schedule_decisions AS d
                JOIN experiments AS e
                    ON e.experiment_id = d.experiment_id
                JOIN jobs AS j
                    ON j.job_id = d.job_id
                WHERE
                    e.defense_config IN (
                        'ilp_anomaly_only',
                        'full'
                    )
                    AND d.delta_j > ?
                ORDER BY
                    e.defense_config,
                    d.delta_j DESC
                """,
                (TAU,),
            ).fetchall()

    except sqlite3.Error as exc:
        print(f"ERROR: Could not query database: {exc}")
        return 1

    print(
        f"{'config':<20}"
        f"{'inj':>5}"
        f"{'flagged':>10}"
        f"{'delta_j':>16}"
        f"{'excess_over_tau':>20}"
    )
    print("-" * 71)

    excess_values = []

    for config, injected, flagged, delta in rows:
        excess = delta - TAU
        excess_values.append(excess)

        print(
            f"{config:<20}"
            f"{int(bool(injected)):>5}"
            f"{str(flagged):>10}"
            f"{delta:>16.9f}"
            f"{excess:>20.2e}"
        )

    tiny = sum(
        1 for excess in excess_values
        if excess < TOLERANCE
    )

    print()
    print(f"Threshold (TAU): {TAU}")
    print(f"Total violations: {len(excess_values)}")
    print(
        f"Violations below {TOLERANCE:g} excess: "
        f"{tiny}/{len(excess_values)}"
    )

    print()
    print(
        "IMPORTANT: The strict ASR scorer counts every "
        "delta_j > TAU as a success."
    )
    print(
        "Tiny numerical overshoots are still counted, "
        "even when below the diagnostic tolerance."
    )

    if not rows:
        print("No persisted decisions exceed the configured threshold.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
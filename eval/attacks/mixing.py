"""Turn a benign job set into an attacked one at a chosen injection ratio.

Pure (no database), so it can be used and tested without SQLAlchemy.
`eval/experiments/injection_runner.py` schedules the results; the design
rules that make runs comparable are documented there (paired, nested,
distinct ids).
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from eval.attacks.payloads import payloads_for
from src.simulator.ids import deterministic_uuid
from src.simulator.models import AttackFamily, Job

_MAX_DESCRIPTION_LEN = 4096  # Job.description max_length


def mix_attacks(benign_jobs: Sequence[Job], *, ratio: float, seed: int) -> list[Job]:
    """Return `benign_jobs` with `round(len * ratio)` of them replaced by
    attacked copies. Pure and deterministic in `(benign_jobs, ratio, seed)`.

    Raises:
        ValueError: `ratio` outside `[0, 1]`, an empty job set, or a job in
            `benign_jobs` that is already labeled as an attack.
    """
    if not 0.0 <= ratio <= 1.0:
        raise ValueError("ratio must be in [0.0, 1.0]")
    if not benign_jobs:
        raise ValueError("benign_jobs must be non-empty")
    if any(job.is_synthetic_attack for job in benign_jobs):
        raise ValueError("benign_jobs must not already contain attack-labeled jobs")

    num_attacked = round(len(benign_jobs) * ratio)
    order = list(range(len(benign_jobs)))
    random.Random(seed).shuffle(order)

    families = list(AttackFamily)
    mixed = list(benign_jobs)
    for rank, job_index in enumerate(order[:num_attacked]):
        family = families[rank % len(families)]
        library = payloads_for(family)
        payload = library[random.Random(f"{seed}/{rank}").randrange(len(library))]

        original = benign_jobs[job_index]
        room = _MAX_DESCRIPTION_LEN - len(payload.text) - 1
        description = f"{original.description[: max(room, 0)]} {payload.text}".strip()
        mixed[job_index] = original.model_copy(
            update={
                "job_id": deterministic_uuid("attack", seed, original.job_id),
                "description": description,
                "is_synthetic_attack": True,
                "attack_payload_type": family,
            }
        )
    return mixed


__all__ = ["mix_attacks"]

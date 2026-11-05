"""Adversarial regression — re-runs the whole payload library (blueprint §15).

Marked `adversarial`; CI runs this folder whenever `src/guard/`, `src/llm/`,
`src/anomaly/` or `eval/attacks/` changes. Two jobs:

1. Pin the library: if any payload text changes, `library_digest()` changes,
   and this test fails until `PAYLOAD_LIBRARY_VERSION` and the pinned digest
   are updated *together* — so a results table can never silently mix two
   payload sets.
2. Check every payload still builds a valid, correctly labeled attack job
   (ground-truth label intact). Once `src/guard/` and `src/anomaly/` exist,
   extend this file to assert each payload is flagged under C1..C4 and to
   re-run them through the pipeline.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from eval.attacks.payloads import (
    PAYLOAD_LIBRARY,
    PAYLOAD_LIBRARY_VERSION,
    AttackPayload,
    library_digest,
    payloads_for,
)
from src.simulator.models import AttackFamily, Job, ResourceDemand, Task

pytestmark = pytest.mark.adversarial

_PINNED_VERSION = "1.0.0"
_PINNED_DIGEST = "0fe3b8982807c6db0653416e8e779e95cfe3d2d00d49c180b96a139f4c284c64"


def _job_carrying(payload_text: str, family: AttackFamily) -> Job:
    return Job(
        tenant_id=uuid4(),
        description=f"synthetic benign job {payload_text}",
        tasks=(
            Task(
                task_name="t",
                demand=ResourceDemand(cpu=1.0, mem_gb=1.0, disk_gb=0.0, net_mbps=0.0),
                est_duration_s=10,
            ),
        ),
        is_synthetic_attack=True,
        attack_payload_type=family,
    )


def test_library_is_pinned() -> None:
    assert PAYLOAD_LIBRARY_VERSION == _PINNED_VERSION
    assert library_digest() == _PINNED_DIGEST, (
        "payload text changed — bump PAYLOAD_LIBRARY_VERSION and re-pin the digest "
        "so earlier results are not compared against a different payload set"
    )


@pytest.mark.parametrize("family", list(AttackFamily))
def test_every_family_is_represented(family: AttackFamily) -> None:
    assert payloads_for(family)


@pytest.mark.parametrize("payload", PAYLOAD_LIBRARY, ids=lambda p: p.payload_id)
def test_every_payload_builds_a_valid_labeled_job(payload: AttackPayload) -> None:
    job = _job_carrying(payload.text, payload.family)

    assert job.is_synthetic_attack
    assert job.attack_payload_type is payload.family
    assert payload.text in job.description

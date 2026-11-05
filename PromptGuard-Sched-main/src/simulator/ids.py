"""Deterministic identifiers for reproducible experiments.

`uuid4()` ids reach the LLM prompt (`job_id`, `tenant_id`, node ids — see
`src/encoder/state_encoder.py`), so random ids make an otherwise seeded run
produce different prompts, and therefore different model/echo outputs, on
every execution. Deriving ids from `(namespace, parts...)` with UUIDv5 makes
the same seed yield byte-identical prompts, which multi-seed experiments and
paired significance tests (blueprint §12) depend on.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

_ID_NAMESPACE: UUID = uuid5(NAMESPACE_URL, "promptguard-sched/deterministic-ids")
_PART_SEPARATOR: str = "/"


def deterministic_uuid(*parts: str | int) -> UUID:
    """Stable UUIDv5 derived from `parts`; same parts -> same UUID."""
    if not parts:
        raise ValueError("deterministic_uuid requires at least one part")
    return uuid5(_ID_NAMESPACE, _PART_SEPARATOR.join(str(part) for part in parts))

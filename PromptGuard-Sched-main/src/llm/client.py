"""LLM candidate-generation stage (blueprint §7 `src/llm/`).

This module is the glue `README.md §8 "Where to start" step 5` refers to:
it takes an `EncodedState` from `src/encoder/`, drives an `LLMBackend`
(`src/llm/backends.py`) with the response contract from `src/llm/schema.py`,
and hands back a validated `AllocationProposal` for `src/ilp/` — never raw
model text past this module's boundary (README §7: no bare dicts/strings
between pipeline stages).

What this module deliberately does NOT do:
- No DB I/O and no latency timing. Like the encoder (see its docstring),
  this is a pure(-ish) function of its inputs plus one network/GPU call —
  `src/scheduler/pipeline.py` is the orchestrator that times it and writes
  `stage_latencies` / `schedule_decisions`, per blueprint §8 rule #2.
- No defense-config branching. `defense_config` has already shaped the
  *prompt* upstream in `src/encoder/`; this module just generates and
  parses a candidate for whatever prompt it is given.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.encoder.state_encoder import EncodedState
from src.llm.backends import LLMBackend
from src.llm.schema import (
    RESPONSE_SCHEMA_INSTRUCTIONS,
    AllocationProposal,
    ProposalParseError,
    parse_allocation_proposal,
)

# Retries are for *malformed output* (a model ignoring the schema
# instructions), never for backend/network failures — those should
# propagate immediately rather than be silently retried against a GPU
# that may already be under load (README §5: single 6GB card, shared
# across concurrent jobs in load tests per blueprint §15).
MAX_PARSE_RETRIES: int = 2
DEFAULT_MAX_NEW_TOKENS: int = 256

_RETRY_REINFORCEMENT_NOTE: str = (
    "\n\nYour previous response could not be parsed as the required JSON "
    "object. Respond again, following the schema exactly — JSON only, no "
    "markdown fences, no prose."
)


class LLMCandidateError(RuntimeError):
    """Raised when no schema-valid `AllocationProposal` could be obtained
    within `MAX_PARSE_RETRIES` attempts.

    Callers (`src/scheduler/pipeline.py`) should treat this as a recorded
    pipeline failure for the job's `trace_id`, not let it crash the whole
    experiment run — a model's inability to follow the schema is itself a
    measurable outcome (blueprint §12 robustness/false-positive analysis).
    """


@dataclass(frozen=True, slots=True)
class LLMCandidateResult:
    """What `src/scheduler/pipeline.py` needs from this stage.

    `raw_response` is kept (not discarded after parsing) because
    `schedule_decisions.llm_candidate` is specified as "raw LLM output,
    kept for audit" (blueprint §9 / `db/migrations/models.py` docstring) —
    the orchestrator persists this verbatim, not a re-serialization of
    `proposal`.
    """

    proposal: AllocationProposal
    raw_response: str
    model_id: str
    attempts: int


class LLMCandidateGenerator:
    """Drives an `LLMBackend` to produce a validated `AllocationProposal`.

    Stateless aside from holding a reference to its `LLMBackend` — same
    instantiate-once-reuse-across-jobs pattern as `TrustAwareStateEncoder`
    and `IlpAllocationRefiner`.
    """

    def __init__(self, backend: LLMBackend) -> None:
        self._backend = backend

    @property
    def model_id(self) -> str:
        return self._backend.model_id

    def generate_candidate(
        self,
        *,
        encoded_state: EncodedState,
        max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    ) -> LLMCandidateResult:
        """Generate and parse one job's allocation candidate.

        Args:
            encoded_state: output of `TrustAwareStateEncoder.encode(...)`
                for this job. `encoded_state.system_message` and
                `.user_message` are combined with the fixed schema
                instructions to form the prompt — this module does not
                re-decide how tenant text is isolated, it only consumes
                the encoder's finished messages.
            max_new_tokens: forwarded to `LLMBackend.generate`.

        Raises:
            LLMCandidateError: no schema-valid response was obtained after
                `1 + MAX_PARSE_RETRIES` attempts. The original
                `ProposalParseError` is chained via `__cause__`.
        """
        prompt = _build_prompt(encoded_state)
        last_error: ProposalParseError | None = None

        for attempt in range(1, MAX_PARSE_RETRIES + 2):  # first try + retries
            raw_response = self._backend.generate(prompt, max_new_tokens=max_new_tokens)
            try:
                proposal = parse_allocation_proposal(raw_response)
            except ProposalParseError as exc:
                last_error = exc
                prompt = prompt + _RETRY_REINFORCEMENT_NOTE
                continue
            return LLMCandidateResult(
                proposal=proposal,
                raw_response=raw_response,
                model_id=self._backend.model_id,
                attempts=attempt,
            )

        raise LLMCandidateError(
            f"model_id={self._backend.model_id!r} produced no schema-valid "
            f"AllocationProposal after {MAX_PARSE_RETRIES + 1} attempts"
        ) from last_error


def _build_prompt(encoded_state: EncodedState) -> str:
    """Assemble the full prompt sent to `LLMBackend.generate`.

    Kept as a free function (not a method) since it has no dependency on
    backend state — trivially unit-testable on its own, and it is exactly
    the string `DeterministicEchoBackend`'s regex-based stand-in and any
    real `HuggingFaceLLMBackend` both receive, so a test asserting prompt
    shape does not need either backend instantiated.
    """
    return "\n\n".join(
        (
            encoded_state.system_message,
            encoded_state.user_message,
            RESPONSE_SCHEMA_INSTRUCTIONS,
        )
    )

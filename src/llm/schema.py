"""Structured contract for what the LLM candidate-generation stage produces.

Blueprint §7 pipeline: `LLM Candidate Generation → Statistical Anomaly Check
→ ILP Refinement`. The anomaly and ILP stages need a typed, bounded object to
consume — never a raw string and never a bare dict (README §7) — so this
module defines that contract and the (deliberately narrow) parsing logic
that turns raw model output into it.

Design decision worth stating explicitly: the LLM is asked for *shares*
(fraction of each resource's requested demand it recommends granting, in
`[0.0, 1.0]`), not absolute allocations. Bounding the schema this way means
a successfully-parsed response can never itself encode an out-of-range
allocation — the injection attack (blueprint §5) has to manifest as
"propose 1.0 (grant everything)" repeatedly across resources, not as an
unbounded number, which keeps `AllocationProposal` a meaningful anomaly
signal for `src/anomaly/` rather than something that needs its own
sanitization pass first.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

# --- Response contract -------------------------------------------------------

RESPONSE_SCHEMA_INSTRUCTIONS: str = (
    "Respond with a single JSON object and nothing else — no markdown "
    "fences, no prose before or after it. The object must have exactly "
    "these keys:\n"
    '  "cpu_share": number in [0.0, 1.0]\n'
    '  "mem_share": number in [0.0, 1.0]\n'
    '  "disk_share": number in [0.0, 1.0]\n'
    '  "net_share": number in [0.0, 1.0]\n'
    '  "rationale": short string, at most 240 characters\n'
    "Each *_share is the fraction of that resource's requested demand you "
    "recommend granting this job, given the cluster state above. 1.0 means "
    "grant the full request; 0.0 means grant none."
)


class AllocationProposal(BaseModel):
    """The LLM's proposed allocation for one job, as fractions of demand.

    Frozen and share-bounded (blueprint note above) — this is the object
    `src/anomaly/` measures Δ(J)-relevant deviation against and `src/ilp/`
    takes as a refinement starting point, never the raw model string.
    """

    model_config = {"frozen": True}

    cpu_share: float = Field(ge=0.0, le=1.0)
    mem_share: float = Field(ge=0.0, le=1.0)
    disk_share: float = Field(ge=0.0, le=1.0)
    net_share: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=240)

    def mean_share(self) -> float:
        """Unweighted mean across resources — a cheap scalar summary used by
        the guard/anomaly layers before the full DRF-based Δ(J) is computed
        downstream in `src/scheduler/fairness.py`.
        """
        return (self.cpu_share + self.mem_share + self.disk_share + self.net_share) / 4.0


class ProposalParseError(ValueError):
    """Raised when raw model output cannot be parsed into an `AllocationProposal`.

    Callers (see `src/llm/client.py`) catch this and record the failure
    rather than let it propagate — a malformed response is itself a
    measurable outcome (feeds the false-positive/robustness analysis in
    blueprint §12), not a crash.
    """


def extract_json_object(text: str) -> str:
    """Extract the first balanced top-level `{...}` substring from `text`.

    Models reliably wrap JSON in prose or markdown fences despite
    instructions not to. Rather than trust `json.loads` on the raw string,
    scan for the first balanced brace pair — the cheapest thing that is
    still correct in the presence of nested objects, and correct even when
    quoted braces appear inside `rationale` strings (brace-depth counting
    ignores braces while inside a JSON string literal).

    Raises:
        ProposalParseError: no balanced `{...}` substring is found.
    """
    start = text.find("{")
    if start == -1:
        raise ProposalParseError("no '{' found in model response")

    depth = 0
    in_string = False
    escape_next = False
    for index in range(start, len(text)):
        char = text[index]
        if escape_next:
            escape_next = False
            continue
        if char == "\\" and in_string:
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ProposalParseError("no balanced '{...}' object found in model response")


def parse_allocation_proposal(raw_response: str) -> AllocationProposal:
    """Parse raw LLM text into a validated `AllocationProposal`.

    Raises:
        ProposalParseError: the response has no extractable JSON object, the
            JSON is malformed, or it fails `AllocationProposal` validation
            (missing key, out-of-range share, oversized rationale, etc.).
    """
    json_text = extract_json_object(raw_response)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ProposalParseError(f"extracted text is not valid JSON: {exc}") from exc

    try:
        return AllocationProposal.model_validate(payload)
    except Exception as exc:  # pydantic.ValidationError, re-raised as our own type
        raise ProposalParseError(f"JSON did not match AllocationProposal schema: {exc}") from exc
"""LLM candidate-generation stage (blueprint §7 `src/llm/`).

Public API re-exported here so callers write `from src.llm import
LLMCandidateGenerator` rather than reaching into submodules directly.
"""

from src.llm.backends import (
    ECHO_MODEL_ID_PREFIX,
    DeterministicEchoBackend,
    HuggingFaceLLMBackend,
    LLMBackend,
)
from src.llm.client import LLMCandidateError, LLMCandidateGenerator, LLMCandidateResult
from src.llm.schema import AllocationProposal, ProposalParseError

__all__ = [
    "ECHO_MODEL_ID_PREFIX",
    "AllocationProposal",
    "DeterministicEchoBackend",
    "HuggingFaceLLMBackend",
    "LLMBackend",
    "LLMCandidateError",
    "LLMCandidateGenerator",
    "LLMCandidateResult",
    "ProposalParseError",
]

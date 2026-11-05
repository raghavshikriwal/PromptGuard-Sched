from types import SimpleNamespace

import pytest

from src.llm.client import (
    DEFAULT_MAX_NEW_TOKENS,
    MAX_PARSE_RETRIES,
    LLMCandidateError,
    LLMCandidateGenerator,
)
from src.llm.schema import ProposalParseError


VALID_RESPONSE = (
    '{"cpu_share":0.8,"mem_share":0.7,"disk_share":0.6,'
    '"net_share":0.9,"rationale":"Allocation based on capacity."}'
)


class FakeBackend:
    def __init__(self, responses, model_id="test/fake-model"):
        self.responses = iter(responses)
        self.model_id = model_id
        self.calls = []

    def generate(self, prompt, *, max_new_tokens=256):
        self.calls.append({
            "prompt": prompt,
            "max_new_tokens": max_new_tokens,
        })
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def encoded_state():
    return SimpleNamespace(
        system_message="SYSTEM: cluster capacity is available.",
        user_message="USER: allocate resources for job-123.",
    )


def test_successful_generation_returns_valid_candidate(encoded_state):
    backend = FakeBackend([VALID_RESPONSE])
    generator = LLMCandidateGenerator(backend)

    result = generator.generate_candidate(encoded_state=encoded_state)

    assert result.proposal.cpu_share == 0.8
    assert result.raw_response == VALID_RESPONSE
    assert result.model_id == "test/fake-model"
    assert result.attempts == 1
    assert len(backend.calls) == 1


def test_model_id_property_returns_backend_model_id():
    generator = LLMCandidateGenerator(FakeBackend([VALID_RESPONSE]))

    assert generator.model_id == "test/fake-model"


def test_prompt_contains_system_user_and_schema_instructions(encoded_state):
    backend = FakeBackend([VALID_RESPONSE])
    generator = LLMCandidateGenerator(backend)

    generator.generate_candidate(encoded_state=encoded_state)

    prompt = backend.calls[0]["prompt"]
    assert encoded_state.system_message in prompt
    assert encoded_state.user_message in prompt
    assert "single JSON object" in prompt


def test_custom_max_new_tokens_is_forwarded(encoded_state):
    backend = FakeBackend([VALID_RESPONSE])
    generator = LLMCandidateGenerator(backend)

    generator.generate_candidate(
        encoded_state=encoded_state,
        max_new_tokens=128,
    )

    assert backend.calls[0]["max_new_tokens"] == 128


def test_default_max_new_tokens_is_forwarded(encoded_state):
    backend = FakeBackend([VALID_RESPONSE])
    generator = LLMCandidateGenerator(backend)

    generator.generate_candidate(encoded_state=encoded_state)

    assert backend.calls[0]["max_new_tokens"] == DEFAULT_MAX_NEW_TOKENS


def test_malformed_response_is_retried_and_then_succeeds(encoded_state):
    backend = FakeBackend(["not JSON", VALID_RESPONSE])
    generator = LLMCandidateGenerator(backend)

    result = generator.generate_candidate(encoded_state=encoded_state)

    assert result.attempts == 2
    assert len(backend.calls) == 2
    assert "schema exactly" in backend.calls[1]["prompt"]


def test_all_malformed_responses_raise_candidate_error(encoded_state):
    responses = ["invalid"] * (MAX_PARSE_RETRIES + 1)
    backend = FakeBackend(responses)
    generator = LLMCandidateGenerator(backend)

    with pytest.raises(LLMCandidateError) as exc_info:
        generator.generate_candidate(encoded_state=encoded_state)

    assert len(backend.calls) == MAX_PARSE_RETRIES + 1
    assert isinstance(exc_info.value.__cause__, ProposalParseError)


def test_backend_error_propagates_without_retry(encoded_state):
    backend = FakeBackend([RuntimeError("backend unavailable")])
    generator = LLMCandidateGenerator(backend)

    with pytest.raises(RuntimeError, match="backend unavailable"):
        generator.generate_candidate(encoded_state=encoded_state)

    assert len(backend.calls) == 1


def test_success_after_multiple_retries_reports_correct_attempt_count(encoded_state):
    backend = FakeBackend(["bad response", "still invalid", VALID_RESPONSE])
    generator = LLMCandidateGenerator(backend)

    result = generator.generate_candidate(encoded_state=encoded_state)

    assert result.attempts == 3
    assert len(backend.calls) == 3

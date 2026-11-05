"""Focused tests for environment parsing and cached runtime settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Keep cached settings isolated between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_model_ids_parse_comma_separated_values() -> None:
    settings = Settings(LLM_MODEL_IDS=" model-a, ,model-b ,, ")

    assert settings.llm_model_ids == ("model-a", "model-b")


def test_model_ids_accept_tuple_input_unchanged() -> None:
    model_ids = ("model-a", "model-b")

    settings = Settings(LLM_MODEL_IDS=model_ids)

    assert settings.llm_model_ids == model_ids


def test_float_tuple_fields_parse_comma_separated_values() -> None:
    settings = Settings(
        TAU_ASR_SWEEP="0.10, ,0.50,",
        INJECTION_RATIOS="0.01, 0.10,",
    )

    assert settings.tau_asr_sweep == (0.10, 0.50)
    assert settings.injection_ratios == (0.01, 0.10)


def test_float_tuple_fields_accept_tuple_input_unchanged() -> None:
    sweep = (0.10, 0.50)
    ratios = (0.01, 0.10)

    settings = Settings(TAU_ASR_SWEEP=sweep, INJECTION_RATIOS=ratios)

    assert settings.tau_asr_sweep == sweep
    assert settings.injection_ratios == ratios


def test_empty_tau_asr_sweep_is_rejected() -> None:
    with pytest.raises(ValidationError, match="tau_asr_sweep must not be empty"):
        Settings(TAU_ASR_SWEEP=" , , ")


def test_get_settings_is_cached_until_cache_is_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_PORT", "8123")

    first = get_settings()
    monkeypatch.setenv("API_PORT", "8124")
    second = get_settings()

    assert second is first
    assert second.api_port == 8123

    get_settings.cache_clear()
    third = get_settings()

    assert third is not first
    assert third.api_port == 8124

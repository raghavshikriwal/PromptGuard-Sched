"""Central configuration: environment settings + project-wide named constants.

Blueprint §8 rule #1: `defense_config` is a parameter, never a code branch.
README §6/§7 rule: never hardcode `model_id`, `defense_config`, or thresholds
inside business logic — they come from here (or from `configs/` experiment
specs at runtime), not from magic strings scattered across modules.

Everything a pipeline stage needs to know about *how* to run — which
defense layers are active, which threshold to apply, which model to call —
flows through the `DefenseConfig` enum and `Settings` defined here. No other
module should define its own copy of `TAU_ASR_DEFAULT` or similar.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class DefenseConfig(str, Enum):
    """The five ablation cells from blueprint §10/§12 (C0–C4).

    This is the parameter every pipeline stage switches on — `src/scheduler/`
    passes one of these through `guard`, `encoder`, and `anomaly` on every
    single job. It is never an `if defense_config == "none": ...` string
    comparison scattered across modules; call sites match on this enum.
    """

    NONE = "none"  # C0 — no defense layer active
    GUARD_ONLY = "guard_only"  # C1 — Layer 1 only
    TRUST_ONLY = "trust_only"  # C2 — Layer 2 only
    ILP_ANOMALY_ONLY = "ilp_anomaly_only"  # C3 — Layer 3 only
    FULL = "full"  # C4 — all three layers

    @property
    def guard_active(self) -> bool:
        return self in (DefenseConfig.GUARD_ONLY, DefenseConfig.FULL)

    @property
    def trust_boundary_active(self) -> bool:
        """Layer 2 (trust-aware encoder separation) is structural, not
        optional in the encoder implementation itself — but experiments can
        still compare against a deliberately-degraded encoder that flattens
        system/tenant text together, which is what this flag gates.
        """
        return self in (DefenseConfig.TRUST_ONLY, DefenseConfig.FULL)

    @property
    def ilp_anomaly_active(self) -> bool:
        return self in (DefenseConfig.ILP_ANOMALY_ONLY, DefenseConfig.FULL)


class PipelineStage(str, Enum):
    """Stage labels written into `stage_latencies.stage` (blueprint §9).

    A closed vocabulary here, not a bare string in each module, is what
    keeps `GROUP BY stage` in the P50/P99 latency query from silently
    fracturing into `"encode"` vs `"Encode"` vs `"encoding"`.
    """

    ENCODE = "encode"
    GUARD = "guard"
    LLM = "llm"
    ANOMALY = "anomaly"
    ILP = "ilp"


# --- Metric thresholds & experimental-matrix constants (blueprint §4/§12) --

TAU_ASR_DEFAULT: float = 0.25
TAU_ASR_SWEEP: tuple[float, ...] = (0.10, 0.25, 0.50)
INJECTION_RATIOS: tuple[float, ...] = (0.01, 0.05, 0.10)
DEFAULT_SEED_COUNT: int = 5
PRIORITY_LEVELS: int = 12  # blueprint §11: "12 priority levels"

# blueprint §11 — LLMSched reference numbers, for the baseline validation
# gate (§13). Directional targets only — never force-fit to these.
BASELINE_REFERENCE_AVG_JCT_S: float = 417.9
BASELINE_REFERENCE_CPU_UTILIZATION: float = 0.766
BASELINE_REFERENCE_SLA_VIOLATION_RATE: float = 0.119
BASELINE_REFERENCE_DRF_FAIRNESS: float = 0.823


class Settings(BaseSettings):
    """Runtime settings loaded from environment / `.env` (see `.env.example`).

    Instantiate via `get_settings()` (cached) rather than `Settings()`
    directly, so the whole process shares one parsed, validated config
    instead of re-parsing `.env` in every module that needs a threshold.

    Tuple-typed fields (`llm_model_ids`, `tau_asr_sweep`, `injection_ratios`)
    are annotated `NoDecode`: by default pydantic-settings tries to
    `json.loads()` any env value destined for a non-str field *before*
    handing it to field validators, which would reject `.env`'s plain
    comma-separated form (e.g. `LLM_MODEL_IDS=a,b`) with a `SettingsError`
    ahead of `_split_model_ids` ever running. `NoDecode` opts these three
    fields out of that automatic JSON decode so the raw string reaches the
    `mode="before"` validators below, which do the actual parsing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets --------------------------------------------------------
    hf_token: str = Field(default="", alias="HF_TOKEN")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    # --- Database ---------------------------------------------------------
    database_url: str = Field(
        default="sqlite:///./data/promptguard_sched.db", alias="DATABASE_URL"
    )

    # --- Cache --------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    llm_cache_enabled: bool = Field(default=True, alias="LLM_CACHE_ENABLED")

    # --- Model backends (blueprint §11) ------------------------------------
    llm_model_ids: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("meta-llama/Llama-3.2-3B-Instruct", "Qwen/Qwen2.5-3B-Instruct"),
        alias="LLM_MODEL_IDS",
    )
    llm_quantization: str = Field(default="4bit", alias="LLM_QUANTIZATION")
    llm_device: str = Field(default="cuda", alias="LLM_DEVICE")

    # --- Experiment defaults (never hardcode in business logic) -----------
    tau_asr_default: float = Field(default=TAU_ASR_DEFAULT, alias="TAU_ASR_DEFAULT")
    tau_asr_sweep: Annotated[tuple[float, ...], NoDecode] = Field(
        default=TAU_ASR_SWEEP, alias="TAU_ASR_SWEEP"
    )
    injection_ratios: Annotated[tuple[float, ...], NoDecode] = Field(
        default=INJECTION_RATIOS, alias="INJECTION_RATIOS"
    )
    default_seed_count: int = Field(default=DEFAULT_SEED_COUNT, alias="DEFAULT_SEED_COUNT")
    defense_config_default: DefenseConfig = Field(
        default=DefenseConfig.NONE, alias="DEFENSE_CONFIG_DEFAULT"
    )

    # --- Dataset ------------------------------------------------------------
    cluster_trace_path: str = Field(
        default="./data/google_trace_subset/", alias="CLUSTER_TRACE_PATH"
    )
    trace_days_subset: int = Field(default=2, alias="TRACE_DAYS_SUBSET", ge=1, le=29)

    # --- Runtime --------------------------------------------------------
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")  # noqa: S104
    api_port: int = Field(default=8000, alias="API_PORT", ge=1, le=65535)

    @field_validator("llm_model_ids", mode="before")
    @classmethod
    def _split_model_ids(cls, value: object) -> object:
        """`.env` stores this as a comma-separated string; split before the
        tuple validator runs. Left alone if already an iterable (e.g. when
        `Settings` is constructed directly in tests with a tuple).
        """
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("tau_asr_sweep", "injection_ratios", mode="before")
    @classmethod
    def _split_float_tuple(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(float(part.strip()) for part in value.split(",") if part.strip())
        return value

    @field_validator("tau_asr_sweep")
    @classmethod
    def _sweep_must_contain_default(
        cls, value: tuple[float, ...], info: object
    ) -> tuple[float, ...]:
        if not value:
            raise ValueError("tau_asr_sweep must not be empty")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached `Settings` instance.

    Cached rather than module-level-instantiated so tests can call
    `get_settings.cache_clear()` after monkeypatching environment variables,
    instead of fighting a settings object frozen at import time.
    """
    return Settings()
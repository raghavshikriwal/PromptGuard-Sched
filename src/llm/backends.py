"""Model backends for the LLM candidate-generation stage.

Two implementations, both satisfying the same `LLMBackend` protocol so
`src/llm/client.py` never needs to know which one it's talking to:

1. `HuggingFaceLLMBackend` — real inference against `settings.llm_model_ids`
   (README §5: 4-bit quantized via `bitsandbytes`, RTX 3050 6GB target).
   This is the only backend allowed to appear in a `model_id` recorded on
   a real `Experiment` row.
2. `DeterministicEchoBackend` — no model weights, no GPU. Used by
   `tests/unit` and `tests/integration` (README §5 dev machine may not
   always have the GPU free) and by early pipeline wiring before real
   model access is set up. Its `model_id` is always prefixed
   `"echo-test/"` so it can never be mistaken for a real experiment result
   if it ever ends up in a DB row — `src/llm/client.py` and
   `eval/experiments/` should refuse to start a real run against it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol, runtime_checkable

from src.config import Settings, get_settings

# --- Backend protocol ---------------------------------------------------------


@runtime_checkable
class LLMBackend(Protocol):
    """Minimal interface `src/llm/client.py` depends on.

    Deliberately narrow — one method, one property — so adding a third
    backend (e.g. an API model per blueprint §11's "one API model optional")
    never requires touching the client.
    """

    @property
    def model_id(self) -> str: ...

    def generate(self, prompt: str, *, max_new_tokens: int = 256) -> str:
        """Return raw model text for `prompt`. No parsing, no retries —
        that is `src/llm/client.py`'s job, kept separate so a backend swap
        never touches parsing logic and vice versa.
        """
        ...


# --- Real backend: local HF model, 4-bit quantized --------------------------

# Module-level cache so a `HuggingFaceLLMBackend` for a given `model_id` is
# loaded once per process, not once per job — with a 6GB card (README §5)
# reloading per call is not just slow, it risks OOM under concurrent load
# tests (blueprint §15 Locust/k6 latency suite).
_MODEL_CACHE: dict[str, tuple[object, object]] = {}  # model_id -> (model, tokenizer)


class HuggingFaceLLMBackend:
    """Local Hugging Face causal LM, 4-bit quantized per `Settings`.

    Import of `transformers`/`bitsandbytes`/`torch` is deferred to
    `_load()` rather than module scope: `tests/unit` and CI (which run
    against `DeterministicEchoBackend`) should not need GPU-capable wheels
    installed just to import this module.
    """

    def __init__(self, model_id: str, settings: Settings | None = None) -> None:
        if model_id not in (settings or get_settings()).llm_model_ids:
            raise ValueError(
                f"model_id={model_id!r} is not in settings.llm_model_ids — "
                "add it there (README §7: never hardcode model_id in business "
                "logic) before using it in a real experiment"
            )
        self._model_id = model_id
        self._settings = settings or get_settings()

    @property
    def model_id(self) -> str:
        return self._model_id

    def _load(self) -> tuple[object, object]:
        if self._model_id in _MODEL_CACHE:
            return _MODEL_CACHE[self._model_id]

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        quantization_config = None
        if self._settings.llm_quantization == "4bit":
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )

        tokenizer = AutoTokenizer.from_pretrained(self._model_id)
        model = AutoModelForCausalLM.from_pretrained(
            self._model_id,
            quantization_config=quantization_config,
            device_map=self._settings.llm_device,
            token=self._settings.hf_token or None,
        )
        model.eval()

        _MODEL_CACHE[self._model_id] = (model, tokenizer)
        return model, tokenizer

    def generate(self, prompt: str, *, max_new_tokens: int = 256) -> str:
        import torch

        model, tokenizer = self._load()
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,  # deterministic decoding: reproducibility (blueprint §16)
                pad_token_id=tokenizer.eos_token_id,
            )
        generated_ids = output_ids[0][inputs["input_ids"].shape[1] :]
        return tokenizer.decode(generated_ids, skip_special_tokens=True)


# --- Dev/test backend: deterministic, no weights, no GPU ---------------------

ECHO_MODEL_ID_PREFIX: str = "echo-test/"

_SHARE_PATTERN = re.compile(r"total_demand:.*?cpu=([\d.]+).*?cluster_capacity:.*?cpu=([\d.]+)")


class DeterministicEchoBackend:
    """Seeded, offline stand-in for `LLMBackend` — tests and early wiring only.

    Never registered in `Settings.llm_model_ids`, so `HuggingFaceLLMBackend`'s
    own guard against unlisted model_ids can never accidentally accept an
    echo model_id, and `eval/experiments/` can filter it out with a simple
    `model_id.startswith(ECHO_MODEL_ID_PREFIX)` check before starting a run
    intended for the paper.

    Behavior is intentionally simple and content-independent of any
    instruction-like text in the prompt: it derives a share purely from the
    numeric cpu demand-vs-capacity ratio it can find in the SYSTEM STATE
    block, ignoring everything else. That makes it useless for *measuring*
    prompt-injection susceptibility (it has no susceptibility to measure —
    it isn't reading the tenant narrative at all) but exactly what unit and
    integration tests need: a backend that returns schema-valid, decodable
    JSON without ever downloading model weights.
    """

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed

    @property
    def model_id(self) -> str:
        return f"{ECHO_MODEL_ID_PREFIX}seed-{self._seed}"

    def generate(self, prompt: str, *, max_new_tokens: int = 256) -> str:
        del max_new_tokens  # unused — response length is fixed and small

        match = _SHARE_PATTERN.search(prompt)
        if match:
            demand_cpu, capacity_cpu = float(match.group(1)), float(match.group(2))
            base_share = min(1.0, demand_cpu / capacity_cpu) if capacity_cpu > 0 else 0.5
        else:
            base_share = 0.5

        # Small deterministic per-prompt jitter (stable across repeated calls
        # with the same prompt, varies across different prompts/jobs) so
        # tests exercising multiple jobs don't get byte-identical proposals.
        digest = hashlib.sha256((prompt + str(self._seed)).encode("utf-8")).hexdigest()
        jitter = (int(digest[:8], 16) % 1000) / 10000.0  # in [0.0, 0.1)
        share = max(0.0, min(1.0, base_share + jitter))

        return (
            "{"
            f'"cpu_share": {share:.4f}, "mem_share": {share:.4f}, '
            f'"disk_share": {share:.4f}, "net_share": {share:.4f}, '
            f'"rationale": "deterministic echo backend, seed={self._seed}"'
            "}"
        )
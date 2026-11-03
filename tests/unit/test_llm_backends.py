from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
import sys

import pytest

import src.llm.backends as backends
from src.config import Settings


@pytest.fixture(autouse=True)
def clear_model_cache():
    backends._MODEL_CACHE.clear()
    yield
    backends._MODEL_CACHE.clear()


@pytest.fixture
def hf_settings():
    return Settings(
        LLM_MODEL_IDS=("Qwen/Qwen2.5-3B-Instruct",),
        LLM_QUANTIZATION="4bit",
        LLM_DEVICE="cpu",
        HF_TOKEN="test-token",
    )


class FakeTensor:
    shape = (1, 3)


class FakeBatch(dict):
    def to(self, device):
        self.device_used = device
        return self


class FakeRow:
    def __getitem__(self, item):
        return ("generated-token-ids", item)


class FakeOutput:
    def __getitem__(self, index):
        assert index == 0
        return FakeRow()


class FakeTokenizer:
    def __init__(self, chat_template="fake-template"):
        self.chat_template = chat_template
        self.eos_token_id = 99
        self.template_messages = None
        self.tokenizer_calls = []
        self.decoded_value = None

    def apply_chat_template(self, messages, **kwargs):
        self.template_messages = (messages, kwargs)
        return "formatted chat prompt"

    def __call__(self, text, **kwargs):
        self.tokenizer_calls.append((text, kwargs))
        return FakeBatch(input_ids=FakeTensor())

    def decode(self, generated_ids, **kwargs):
        self.decoded_value = (generated_ids, kwargs)
        return "decoded model response"


class FakeModel:
    device = "cpu"

    def __init__(self):
        self.eval_called = False
        self.generation_kwargs = None

    def eval(self):
        self.eval_called = True

    def generate(self, **kwargs):
        self.generation_kwargs = kwargs
        return FakeOutput()


def install_fake_hf_modules(monkeypatch, tokenizer=None):
    tokenizer = tokenizer or FakeTokenizer()
    model = FakeModel()
    calls = {
        "tokenizer": [],
        "model": [],
        "quantization": [],
    }

    class FakeBitsAndBytesConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            calls["quantization"].append(kwargs)

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model_id):
            calls["tokenizer"].append(model_id)
            return tokenizer

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            calls["model"].append((model_id, kwargs))
            return model

    fake_torch = ModuleType("torch")
    fake_torch.float16 = "fake-float16"
    fake_torch.no_grad = nullcontext

    fake_transformers = ModuleType("transformers")
    fake_transformers.AutoTokenizer = FakeAutoTokenizer
    fake_transformers.AutoModelForCausalLM = FakeAutoModel
    fake_transformers.BitsAndBytesConfig = FakeBitsAndBytesConfig

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    return model, tokenizer, calls


def test_echo_backend_satisfies_backend_protocol():
    backend = backends.DeterministicEchoBackend(seed=7)

    assert isinstance(backend, backends.LLMBackend)


def test_echo_backend_model_id_contains_seed():
    backend = backends.DeterministicEchoBackend(seed=12)

    assert backend.model_id == "echo-test/seed-12"


def test_echo_backend_returns_valid_json():
    import json

    backend = backends.DeterministicEchoBackend(seed=1)
    response = backend.generate("ordinary test prompt")
    payload = json.loads(response)

    assert 0.0 <= payload["cpu_share"] <= 1.0
    assert 0.0 <= payload["mem_share"] <= 1.0
    assert 0.0 <= payload["disk_share"] <= 1.0
    assert 0.0 <= payload["net_share"] <= 1.0
    assert "rationale" in payload


def test_echo_backend_uses_demand_to_capacity_ratio():
    import json

    backend = backends.DeterministicEchoBackend(seed=0)
    response = backend.generate(
        "total_demand: cpu=4, mem=8\n"
        "total capacity: cpu=8 cores, mem=16"
    )
    payload = json.loads(response)

    assert 0.5 <= payload["cpu_share"] < 0.6


def test_echo_backend_clamps_share_at_one():
    import json

    backend = backends.DeterministicEchoBackend(seed=0)
    response = backend.generate(
        "total_demand: cpu=20\n"
        "total capacity: cpu=5 cores"
    )
    payload = json.loads(response)

    assert payload["cpu_share"] == 1.0


def test_echo_backend_uses_fallback_for_missing_capacity():
    import json

    backend = backends.DeterministicEchoBackend(seed=0)
    response = backend.generate("total_demand: cpu=4")
    payload = json.loads(response)

    assert 0.5 <= payload["cpu_share"] < 0.6


def test_echo_backend_uses_fallback_for_zero_capacity():
    import json

    backend = backends.DeterministicEchoBackend(seed=0)
    response = backend.generate(
        "total_demand: cpu=4\n"
        "total capacity: cpu=0 cores"
    )
    payload = json.loads(response)

    assert 0.5 <= payload["cpu_share"] < 0.6


def test_echo_backend_is_deterministic_for_same_prompt():
    backend = backends.DeterministicEchoBackend(seed=42)
    prompt = "total_demand: cpu=4\n total capacity: cpu=8 cores"

    assert backend.generate(prompt) == backend.generate(prompt)


def test_huggingface_backend_rejects_unregistered_model(hf_settings):
    with pytest.raises(ValueError, match="not in settings.llm_model_ids"):
        backends.HuggingFaceLLMBackend(
            "unregistered/model",
            settings=hf_settings,
        )


def test_huggingface_backend_exposes_model_id(hf_settings):
    backend = backends.HuggingFaceLLMBackend(
        "Qwen/Qwen2.5-3B-Instruct",
        settings=hf_settings,
    )

    assert backend.model_id == "Qwen/Qwen2.5-3B-Instruct"


def test_load_uses_four_bit_quantization_and_settings(
    monkeypatch, hf_settings
):
    model, tokenizer, calls = install_fake_hf_modules(monkeypatch)
    backend = backends.HuggingFaceLLMBackend(
        "Qwen/Qwen2.5-3B-Instruct",
        settings=hf_settings,
    )

    loaded_model, loaded_tokenizer = backend._load()

    assert loaded_model is model
    assert loaded_tokenizer is tokenizer
    assert model.eval_called

    assert calls["tokenizer"] == ["Qwen/Qwen2.5-3B-Instruct"]
    assert len(calls["model"]) == 1

    model_id, model_kwargs = calls["model"][0]
    assert model_id == "Qwen/Qwen2.5-3B-Instruct"
    assert model_kwargs["device_map"] == "cpu"
    assert model_kwargs["token"] == "test-token"

    quantization = calls["quantization"][0]
    assert quantization["load_in_4bit"] is True
    assert quantization["bnb_4bit_compute_dtype"] == "fake-float16"
    assert quantization["bnb_4bit_quant_type"] == "nf4"
    assert quantization["bnb_4bit_use_double_quant"] is True


def test_load_caches_model_and_tokenizer(monkeypatch, hf_settings):
    model, tokenizer, calls = install_fake_hf_modules(monkeypatch)
    backend = backends.HuggingFaceLLMBackend(
        "Qwen/Qwen2.5-3B-Instruct",
        settings=hf_settings,
    )

    first = backend._load()
    second = backend._load()

    assert first == second
    assert first == (model, tokenizer)
    assert len(calls["tokenizer"]) == 1
    assert len(calls["model"]) == 1


def test_load_skips_quantization_when_disabled(monkeypatch, hf_settings):
    settings = hf_settings.model_copy(
        update={"llm_quantization": "none"}
    )
    _, _, calls = install_fake_hf_modules(monkeypatch)

    backend = backends.HuggingFaceLLMBackend(
        "Qwen/Qwen2.5-3B-Instruct",
        settings=settings,
    )
    backend._load()

    assert calls["quantization"] == []
    assert calls["model"][0][1]["quantization_config"] is None


def test_generate_uses_chat_template(monkeypatch, hf_settings):
    model, tokenizer, _ = install_fake_hf_modules(monkeypatch)
    backend = backends.HuggingFaceLLMBackend(
        "Qwen/Qwen2.5-3B-Instruct",
        settings=hf_settings,
    )

    result = backend.generate("allocate resources", max_new_tokens=64)

    assert result == "decoded model response"
    assert tokenizer.template_messages[0] == [
        {"role": "user", "content": "allocate resources"}
    ]
    assert tokenizer.template_messages[1]["tokenize"] is False
    assert tokenizer.template_messages[1]["add_generation_prompt"] is True

    tokenized_text, tokenized_kwargs = tokenizer.tokenizer_calls[0]
    assert tokenized_text == "formatted chat prompt"
    assert tokenized_kwargs["add_special_tokens"] is False
    assert tokenized_kwargs["return_tensors"] == "pt"

    generation = model.generation_kwargs
    assert generation["max_new_tokens"] == 64
    assert generation["do_sample"] is False
    assert generation["temperature"] is None
    assert generation["top_p"] is None
    assert generation["top_k"] is None
    assert generation["pad_token_id"] == tokenizer.eos_token_id


def test_generate_falls_back_when_chat_template_is_missing(
    monkeypatch, hf_settings
):
    tokenizer = FakeTokenizer(chat_template=None)
    _, _, _ = install_fake_hf_modules(monkeypatch, tokenizer=tokenizer)

    backend = backends.HuggingFaceLLMBackend(
        "Qwen/Qwen2.5-3B-Instruct",
        settings=hf_settings,
    )
    result = backend.generate("raw prompt")

    assert result == "decoded model response"
    tokenized_text, tokenized_kwargs = tokenizer.tokenizer_calls[0]
    assert tokenized_text == "raw prompt"
    assert tokenized_kwargs["add_special_tokens"] is True




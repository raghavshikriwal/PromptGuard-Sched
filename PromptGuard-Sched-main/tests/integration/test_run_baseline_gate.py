"""Integration tests for the `eval/experiments/run_baseline_gate.py` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.experiments import run_baseline_gate as gate
from src.llm.backends import DeterministicEchoBackend, LLMBackend

_VALID_RESPONSE = (
    '{"cpu_share": 0.5, "mem_share": 0.5, "disk_share": 0.5, "net_share": 0.5, "rationale": "stub"}'
)


class _StubBackend:
    model_id = "stub/real-model"

    def generate(self, prompt: str, *, max_new_tokens: int = 256) -> str:
        return _VALID_RESPONSE


class _BrokenBackend:
    model_id = "broken/model"

    def generate(self, prompt: str, *, max_new_tokens: int = 256) -> str:
        return "not json"


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    database_url = f"sqlite:///{(tmp_path / 'gate.db').as_posix()}"
    return ["--num-jobs", "6", "--num-nodes", "3", "--database-url", database_url, *extra]


def _patch_backend(monkeypatch: pytest.MonkeyPatch, backend: LLMBackend) -> None:
    monkeypatch.setattr(gate, "_build_backend", lambda args: backend)


class TestRunBaselineGate:
    def test_echo_smoke_test_exits_zero_with_banner(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = gate.main(_argv(tmp_path, "--backend", "echo"))

        output = capsys.readouterr().out
        assert exit_code == 0
        assert "SMOKE TEST" in output
        assert "jobs_evaluated=6" in output

    def test_google_trace_requires_a_path(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            gate.main(_argv(tmp_path, "--backend", "echo", "--trace", "google"))

    def test_real_backend_path_prints_a_gate_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _patch_backend(monkeypatch, _StubBackend())

        exit_code = gate.main(_argv(tmp_path, "--backend", "huggingface"))

        output = capsys.readouterr().out
        assert exit_code in (0, 1)
        assert "Baseline validation gate:" in output

    def test_echo_backend_without_echo_flag_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _patch_backend(monkeypatch, DeterministicEchoBackend(seed=0))

        exit_code = gate.main(_argv(tmp_path, "--backend", "huggingface"))

        assert exit_code == 2
        assert "baseline run refused" in capsys.readouterr().err

    def test_all_jobs_failing_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _patch_backend(monkeypatch, _BrokenBackend())

        exit_code = gate.main(_argv(tmp_path, "--backend", "huggingface"))

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "no jobs succeeded" in captured.err

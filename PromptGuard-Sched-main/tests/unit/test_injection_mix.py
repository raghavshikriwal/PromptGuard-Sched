"""Unit tests for `mix_attacks` in `eval/experiments/injection_runner.py`."""

from __future__ import annotations

from collections import Counter

import pytest
from eval.attacks.mixing import mix_attacks
from eval.attacks.payloads import payloads_for
from src.simulator.models import AttackFamily, Job
from src.simulator.trace_loader import SyntheticTraceGenerator

_N = 120


@pytest.fixture
def benign() -> list[Job]:
    return SyntheticTraceGenerator(seed=5).generate(_N)


def _attacked(jobs: list[Job]) -> list[Job]:
    return [job for job in jobs if job.is_synthetic_attack]


class TestMixAttacks:
    @pytest.mark.parametrize("ratio", [0.0, 0.01, 0.05, 0.10, 0.5, 1.0])
    def test_attacked_count_matches_ratio(self, benign: list[Job], ratio: float) -> None:
        mixed = mix_attacks(benign, ratio=ratio, seed=1)
        assert len(mixed) == _N
        assert len(_attacked(mixed)) == round(_N * ratio)

    def test_zero_ratio_returns_the_benign_set_unchanged(self, benign: list[Job]) -> None:
        assert mix_attacks(benign, ratio=0.0, seed=1) == benign

    def test_untouched_jobs_are_identical_and_positions_are_kept(self, benign: list[Job]) -> None:
        mixed = mix_attacks(benign, ratio=0.10, seed=1)
        for original, after in zip(benign, mixed, strict=True):
            if not after.is_synthetic_attack:
                assert after == original

    def test_attacked_copy_changes_only_text_labels_and_id(self, benign: list[Job]) -> None:
        mixed = mix_attacks(benign, ratio=0.10, seed=1)
        for original, after in zip(benign, mixed, strict=True):
            if after.is_synthetic_attack:
                assert after.job_id != original.job_id
                assert after.tasks == original.tasks
                assert after.edges == original.edges
                assert after.tenant_id == original.tenant_id
                assert after.deadline_s == original.deadline_s
                assert after.weight == original.weight
                assert after.priority == original.priority

    def test_attack_label_matches_the_injected_payload(self, benign: list[Job]) -> None:
        for job in _attacked(mix_attacks(benign, ratio=0.5, seed=1)):
            assert job.attack_payload_type is not None
            texts = {p.text for p in payloads_for(job.attack_payload_type)}
            assert any(job.description.endswith(text) for text in texts)

    def test_families_are_balanced(self, benign: list[Job]) -> None:
        counts = Counter(
            job.attack_payload_type for job in _attacked(mix_attacks(benign, ratio=0.5, seed=1))
        )
        assert set(counts) == set(AttackFamily)
        assert set(counts.values()) == {_N // 2 // len(AttackFamily)}

    def test_sets_are_nested_across_ratios(self, benign: list[Job]) -> None:
        small = {job.job_id for job in _attacked(mix_attacks(benign, ratio=0.05, seed=1))}
        large = {job.job_id for job in _attacked(mix_attacks(benign, ratio=0.10, seed=1))}
        assert small and small < large

    def test_a_jobs_attack_does_not_depend_on_the_ratio(self, benign: list[Job]) -> None:
        small = {j.job_id: j for j in _attacked(mix_attacks(benign, ratio=0.05, seed=1))}
        large = {j.job_id: j for j in _attacked(mix_attacks(benign, ratio=0.10, seed=1))}
        for job_id, job in small.items():
            assert large[job_id] == job

    def test_deterministic_per_seed_and_varies_across_seeds(self, benign: list[Job]) -> None:
        assert mix_attacks(benign, ratio=0.1, seed=3) == mix_attacks(benign, ratio=0.1, seed=3)
        assert mix_attacks(benign, ratio=0.1, seed=3) != mix_attacks(benign, ratio=0.1, seed=4)

    def test_long_benign_description_is_truncated_to_fit(self, benign: list[Job]) -> None:
        long_job = benign[0].model_copy(update={"description": "x" * 4096})
        mixed = mix_attacks([long_job], ratio=1.0, seed=1)
        assert len(mixed[0].description) <= 4096
        assert mixed[0].is_synthetic_attack

    @pytest.mark.parametrize("ratio", [-0.1, 1.1])
    def test_rejects_out_of_range_ratio(self, benign: list[Job], ratio: float) -> None:
        with pytest.raises(ValueError, match="ratio"):
            mix_attacks(benign, ratio=ratio, seed=1)

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            mix_attacks([], ratio=0.1, seed=1)

    def test_rejects_input_that_already_contains_attacks(self, benign: list[Job]) -> None:
        once = mix_attacks(benign, ratio=0.1, seed=1)
        with pytest.raises(ValueError, match="already contain"):
            mix_attacks(once, ratio=0.1, seed=2)

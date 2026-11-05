"""Unit tests for `eval/attacks/payloads.py` — the labeled ground truth that
every ASR number in the paper is computed against.
"""

from __future__ import annotations

import base64
import re

import pytest
from eval.attacks.payloads import (
    PAYLOAD_LIBRARY,
    PAYLOAD_LIBRARY_VERSION,
    build_payload_library,
    library_digest,
    make_payload_injector,
    payloads_for,
)
from src.simulator.models import AttackFamily
from src.simulator.trace_loader import SyntheticTraceGenerator

_MAX_DESCRIPTION_LEN = 4096  # Job.description max_length


class TestLibraryShape:
    def test_every_family_has_payloads(self) -> None:
        for family in AttackFamily:
            assert len(payloads_for(family)) >= 10, family

    def test_ids_and_texts_are_unique(self) -> None:
        assert len({p.payload_id for p in PAYLOAD_LIBRARY}) == len(PAYLOAD_LIBRARY)
        assert len({p.text for p in PAYLOAD_LIBRARY}) == len(PAYLOAD_LIBRARY)

    def test_id_carries_the_family_label(self) -> None:
        for payload in PAYLOAD_LIBRARY:
            assert payload.payload_id.startswith(payload.family.value)

    def test_payloads_are_non_empty_and_fit_a_job_description(self) -> None:
        for payload in PAYLOAD_LIBRARY:
            assert payload.text.strip()
            assert len(payload.text) < _MAX_DESCRIPTION_LEN // 4

    def test_every_payload_records_the_library_version(self) -> None:
        assert {p.library_version for p in PAYLOAD_LIBRARY} == {PAYLOAD_LIBRARY_VERSION}

    def test_build_is_deterministic(self) -> None:
        assert build_payload_library() == PAYLOAD_LIBRARY
        assert library_digest() == library_digest()


class TestFamilyContent:
    def test_system_tag_spoofing_uses_fake_system_markup(self) -> None:
        pattern = re.compile(r"<system>|\[SYSTEM\]|SYSTEM OVERRIDE|<\|im_start\|>system")
        assert all(pattern.search(p.text) for p in payloads_for(AttackFamily.SYSTEM_TAG_SPOOFING))

    def test_direct_override_tries_to_cancel_prior_instructions(self) -> None:
        pattern = re.compile(r"ignore|disregard|forget|override", re.IGNORECASE)
        assert all(pattern.search(p.text) for p in payloads_for(AttackFamily.DIRECT_OVERRIDE))

    def test_obfuscated_payloads_hide_the_plain_phrase(self) -> None:
        assert all(
            "Ignore all previous instructions" not in p.text
            for p in payloads_for(AttackFamily.OBFUSCATED_VARIANT)
        )

    def test_obfuscated_base64_payload_decodes_to_the_override(self) -> None:
        encoded = [
            p.text.split(": ", 1)[1]
            for p in payloads_for(AttackFamily.OBFUSCATED_VARIANT)
            if p.text.startswith("Decode this base64")
        ]
        assert encoded
        assert all(
            base64.b64decode(item).decode().startswith("Ignore all previous instructions")
            for item in encoded
        )


class TestInjector:
    def test_appends_a_payload_of_the_requested_family(self) -> None:
        inject = make_payload_injector(seed=1)
        result = inject("benign job", AttackFamily.ROLE_CONFUSION)

        assert result.startswith("benign job ")
        suffix = result[len("benign job ") :]
        assert suffix in {p.text for p in payloads_for(AttackFamily.ROLE_CONFUSION)}

    def test_same_seed_reproduces_the_same_choices(self) -> None:
        first = make_payload_injector(seed=7)
        second = make_payload_injector(seed=7)
        calls = [AttackFamily.DIRECT_OVERRIDE, AttackFamily.OBFUSCATED_VARIANT] * 3
        assert [first("x", f) for f in calls] == [second("x", f) for f in calls]

    @pytest.mark.parametrize("ratio", [0.01, 0.05, 0.10])
    def test_plugs_into_the_trace_generator_at_each_injection_ratio(self, ratio: float) -> None:
        jobs = SyntheticTraceGenerator(seed=3).generate(
            200, injection_ratio=ratio, attack_payload_injector=make_payload_injector(seed=3)
        )

        attacked = [job for job in jobs if job.is_synthetic_attack]
        assert len(attacked) == round(200 * ratio)
        for job in attacked:
            assert job.attack_payload_type is not None
            texts = {p.text for p in payloads_for(job.attack_payload_type)}
            assert any(text in job.description for text in texts)
        for job in jobs:
            if not job.is_synthetic_attack:
                assert job.description == "synthetic benign job"

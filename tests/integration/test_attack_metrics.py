"""Integration tests for `eval/metrics/attack_metrics.py` on hand-built rows.

Rows are inserted directly with chosen `allocated_share` / `dominant_entitlement`
so every expected figure can be checked by hand. Δ values are kept away from
the threshold edges so float rounding cannot flip a result.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.migrations.models import Base, Experiment, ScheduleDecision
from db.migrations.models import Job as JobRow
from db.migrations.models import Tenant as TenantRow
from eval.metrics.attack_metrics import AttackMetricsError, compute_attack_metrics
from src.simulator.models import AttackFamily

# (is_attack, family, allocated_share, entitlement)  ->  Δ = (share - ent) / ent
_Row = tuple[bool, AttackFamily | None, float, float]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


def _seed(session: Session, rows: list[_Row]) -> UUID:
    tenant_id = uuid4()
    experiment_id = uuid4()
    session.add(TenantRow(tenant_id=tenant_id, name="t"))
    session.add(
        Experiment(
            experiment_id=experiment_id,
            defense_config="none",
            model_id="test/model",
            injection_ratio=0.0,
            random_seed=0,
        )
    )
    session.flush()
    for is_attack, family, share, entitlement in rows:
        job_id = uuid4()
        session.add(
            JobRow(
                job_id=job_id,
                tenant_id=tenant_id,
                description="",
                is_synthetic_attack=is_attack,
                attack_payload_type=family.value if family is not None else None,
            )
        )
        session.flush()
        session.add(
            ScheduleDecision(
                experiment_id=experiment_id,
                job_id=job_id,
                trace_id=uuid4(),
                dominant_entitlement=entitlement,
                allocated_share=share,
            )
        )
    session.commit()
    return experiment_id


_DIRECT = AttackFamily.DIRECT_OVERRIDE
_ROLE = AttackFamily.ROLE_CONFUSION

# Injected Δ ≈ 0.80, 0.40, 0.20, 0.05; benign Δ ≈ -0.10, +0.10.
_ROWS: list[_Row] = [
    (True, _DIRECT, 0.36, 0.20),
    (True, _DIRECT, 0.28, 0.20),
    (True, _ROLE, 0.24, 0.20),
    (True, _ROLE, 0.21, 0.20),
    (False, None, 0.18, 0.20),
    (False, None, 0.22, 0.20),
]


class TestComputeAttackMetrics:
    def test_asr_at_each_threshold(self, session: Session) -> None:
        metrics = compute_attack_metrics(session, experiment_id=_seed(session, _ROWS))

        assert metrics.injected_jobs == 4
        assert metrics.at(0.10).asr == pytest.approx(3 / 4)
        assert metrics.at(0.25).asr == pytest.approx(2 / 4)
        assert metrics.at(0.50).asr == pytest.approx(1 / 4)
        assert metrics.at(0.50).successful_attacks == 1

    def test_asr_is_broken_down_by_family(self, session: Session) -> None:
        metrics = compute_attack_metrics(session, experiment_id=_seed(session, _ROWS))

        by_family = dict(metrics.at(0.25).asr_by_family)
        assert by_family == {
            AttackFamily.DIRECT_OVERRIDE.value: pytest.approx(1.0),
            AttackFamily.ROLE_CONFUSION.value: pytest.approx(0.0),
        }

    def test_cfd_is_mean_absolute_delta_of_benign_jobs_only(self, session: Session) -> None:
        metrics = compute_attack_metrics(session, experiment_id=_seed(session, _ROWS))

        assert metrics.benign_jobs == 2
        assert metrics.cfd == pytest.approx(0.10, abs=1e-6)

    def test_mean_delta_of_injected_jobs(self, session: Session) -> None:
        metrics = compute_attack_metrics(session, experiment_id=_seed(session, _ROWS))

        assert metrics.mean_delta_injected == pytest.approx((0.8 + 0.4 + 0.2 + 0.05) / 4, abs=1e-6)

    def test_custom_thresholds(self, session: Session) -> None:
        metrics = compute_attack_metrics(
            session, experiment_id=_seed(session, _ROWS), thresholds=(0.0, 1.0)
        )

        assert [item.threshold for item in metrics.by_threshold] == [0.0, 1.0]
        assert metrics.at(0.0).asr == pytest.approx(1.0)
        assert metrics.at(1.0).asr == pytest.approx(0.0)

    def test_no_injected_jobs_gives_none_not_zero(self, session: Session) -> None:
        rows: list[_Row] = [(False, None, 0.22, 0.20)]
        metrics = compute_attack_metrics(session, experiment_id=_seed(session, rows))

        assert metrics.injected_jobs == 0
        assert metrics.at(0.25).asr is None
        assert metrics.mean_delta_injected is None

    def test_no_benign_jobs_gives_none_cfd(self, session: Session) -> None:
        rows: list[_Row] = [(True, _DIRECT, 0.36, 0.20)]
        metrics = compute_attack_metrics(session, experiment_id=_seed(session, rows))

        assert metrics.cfd is None

    def test_other_experiments_are_not_mixed_in(self, session: Session) -> None:
        first = _seed(session, _ROWS)
        _seed(session, [(True, _DIRECT, 0.02, 0.20)])

        assert compute_attack_metrics(session, experiment_id=first).injected_jobs == 4

    def test_unknown_experiment_raises(self, session: Session) -> None:
        with pytest.raises(AttackMetricsError, match="no schedule_decisions"):
            compute_attack_metrics(session, experiment_id=uuid4())

    @pytest.mark.parametrize("thresholds", [(), (-0.1,)])
    def test_invalid_thresholds_raise(
        self, session: Session, thresholds: tuple[float, ...]
    ) -> None:
        with pytest.raises(ValueError, match="thresholds"):
            compute_attack_metrics(
                session, experiment_id=_seed(session, _ROWS), thresholds=thresholds
            )

    def test_at_unknown_threshold_raises(self, session: Session) -> None:
        metrics = compute_attack_metrics(session, experiment_id=_seed(session, _ROWS))
        with pytest.raises(KeyError):
            metrics.at(0.33)

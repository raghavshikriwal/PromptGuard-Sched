"""Tests for the persisted benign-control comparison CLI."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from db.migrations.models import Base, Experiment, Job, ScheduleDecision
from eval.experiments import benign_control
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def session(tmp_path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'benign-control.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


def _add_decision(
    session: Session,
    *,
    config: str,
    attacked: bool,
    delta: float | None,
) -> None:
    experiment = Experiment(
        defense_config=config,
        model_id="test/model",
        injection_ratio=0.5,
        random_seed=7,
    )
    job = Job(
        description=f"{'injected' if attacked else 'benign'} job",
        is_synthetic_attack=attacked,
    )
    session.add_all([experiment, job])
    session.flush()
    entitlement = 0.0 if delta is None else 1.0
    allocation = 0.0 if delta is None else 1.0 + delta
    session.add(
        ScheduleDecision(
            experiment_id=experiment.experiment_id,
            job_id=job.job_id,
            trace_id=uuid4(),
            dominant_entitlement=entitlement,
            allocated_share=allocation,
        )
    )
    session.flush()


class TestBenignControl:
    def test_reports_sorted_success_rates_and_skips_null_deltas(
        self, session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _add_decision(session, config="full", attacked=True, delta=0.8)
        _add_decision(session, config="full", attacked=True, delta=0.1)
        _add_decision(session, config="full", attacked=False, delta=0.6)
        _add_decision(session, config="full", attacked=False, delta=0.1)
        _add_decision(session, config="none", attacked=False, delta=0.9)
        session.commit()

        monkeypatch.setattr(
            "sys.argv", ["benign_control", "--database-url", "sqlite://", "--tau", "0.5"]
        )
        monkeypatch.setattr(benign_control, "create_engine", lambda _url: session.get_bind())

        assert benign_control.main() == 0
        output = capsys.readouterr().out
        assert "Success rate = share of jobs with delta_J > 0.5" in output
        assert output.index("full") < output.index("none")
        assert "0.500" in output
        assert "n_inj=2, n_ben=2" in output
        assert "nan" in output

    def test_null_delta_rows_are_ignored(self, monkeypatch, capsys) -> None:
        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, _statement):
                return SimpleNamespace(all=lambda: [("none", True, None)])

        monkeypatch.setattr(benign_control, "create_engine", lambda _url: object())
        monkeypatch.setattr(benign_control, "Session", lambda _engine: FakeSession())
        monkeypatch.setattr("sys.argv", ["benign_control", "--database-url", "sqlite://"])

        assert benign_control.main() == 0
        output = capsys.readouterr().out
        assert "config" in output
        assert "none" not in output

    def test_empty_database_prints_headers(self, tmp_path, monkeypatch, capsys) -> None:
        database_url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
        engine = create_engine(database_url)
        Base.metadata.create_all(engine)
        engine.dispose()
        monkeypatch.setattr("sys.argv", ["benign_control", "--database-url", database_url])

        assert benign_control.main() == 0
        output = capsys.readouterr().out
        assert "config" in output
        assert "injected" in output
        assert "benign" in output
        assert "gap" in output

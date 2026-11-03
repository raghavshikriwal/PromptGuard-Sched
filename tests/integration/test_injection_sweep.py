"""End-to-end: benign set -> attacked variants -> pipeline -> DB -> ASR/CFD.

Echo backend, in-memory SQLite. The echo backend ignores job text, so this
checks plumbing and bookkeeping (labels, ratios, ids, metrics wiring), not
whether injection works — that needs a real model.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from db.migrations.models import Base, Experiment
from db.migrations.models import Job as JobRow
from eval.experiments import run_injection_sweep as sweep
from eval.experiments.baseline_runner import BaselineExperimentRunner
from eval.experiments.injection_runner import run_injection_sweep
from eval.metrics.attack_metrics import compute_attack_metrics
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from src.config import DefenseConfig
from src.encoder.state_encoder import TrustAwareStateEncoder
from src.ilp.refine import IlpAllocationRefiner
from src.llm.backends import DeterministicEchoBackend
from src.llm.client import LLMCandidateGenerator
from src.simulator.cluster_generator import size_cluster_for_target_utilization
from src.simulator.trace_loader import SyntheticTraceGenerator

_NUM_JOBS = 20
_SEED = 0


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


def _runner() -> BaselineExperimentRunner:
    return BaselineExperimentRunner(
        encoder=TrustAwareStateEncoder(),
        llm_generator=LLMCandidateGenerator(DeterministicEchoBackend(seed=_SEED)),
        ilp_refiner=IlpAllocationRefiner(),
    )


class TestRunInjectionSweep:
    def test_one_experiment_per_ratio_with_matching_labels(self, session: Session) -> None:
        benign = SyntheticTraceGenerator(seed=_SEED).generate(_NUM_JOBS)
        cluster = size_cluster_for_target_utilization(benign, target_utilization=0.766, num_nodes=4)
        ratios = (0.0, 0.10, 0.50)

        results = run_injection_sweep(
            session,
            _runner(),
            benign_jobs=benign,
            cluster_state=cluster,
            defense_config=DefenseConfig.NONE,
            seed=_SEED,
            ratios=ratios,
            allow_echo_backend=True,
        )

        assert [result.ratio for result in results] == list(ratios)
        for result in results:
            assert result.run.jobs_failed == ()
            experiment = session.get(Experiment, result.run.experiment_id)
            assert experiment is not None
            assert float(experiment.injection_ratio) == pytest.approx(result.ratio)
            metrics = compute_attack_metrics(session, experiment_id=result.run.experiment_id)
            assert metrics.injected_jobs == round(_NUM_JOBS * result.ratio)
            assert metrics.injected_jobs + metrics.benign_jobs == _NUM_JOBS

    def test_attack_labels_are_stored_in_the_jobs_table(self, session: Session) -> None:
        benign = SyntheticTraceGenerator(seed=_SEED).generate(_NUM_JOBS)
        cluster = size_cluster_for_target_utilization(benign, target_utilization=0.766, num_nodes=4)

        run_injection_sweep(
            session,
            _runner(),
            benign_jobs=benign,
            cluster_state=cluster,
            defense_config=DefenseConfig.NONE,
            seed=_SEED,
            ratios=(0.10, 0.50),
            allow_echo_backend=True,
        )

        attacked_rows = session.execute(
            select(func.count()).select_from(JobRow).where(JobRow.is_synthetic_attack.is_(True))
        ).scalar_one()
        # 10% and 50% sets are nested, so the union is the 50% set.
        assert attacked_rows == round(_NUM_JOBS * 0.50)


class TestRunInjectionSweepCli:
    def _argv(self, tmp_path: Path, *extra: str) -> list[str]:
        url = f"sqlite:///{(tmp_path / 'sweep.db').as_posix()}"
        return ["--num-jobs", "10", "--num-nodes", "3", "--database-url", url, *extra]

    def test_echo_run_prints_banner_and_table(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = sweep.main(self._argv(tmp_path, "--ratios", "0", "0.1", "0.5"))

        output = capsys.readouterr().out
        assert exit_code == 0
        assert "SMOKE TEST" in output
        assert "ASR@0.25" in output
        assert "payload library v" in output

    def test_echo_backend_without_echo_flag_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sweep, "_build_backend", lambda args: DeterministicEchoBackend(seed=0))

        exit_code = sweep.main(self._argv(tmp_path, "--backend", "huggingface"))

        assert exit_code == 2
        assert "injection sweep refused" in capsys.readouterr().err

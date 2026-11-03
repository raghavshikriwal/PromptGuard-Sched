"""Unit and orchestration tests for ablation reporting and CLI paths."""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from db.migrations.models import Base, Experiment, Job, ScheduleDecision, StageLatency
from eval.experiments import run_ablation as ablation
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.config import DefenseConfig


@pytest.fixture
def session(tmp_path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'ablation-reporting.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


def _experiment(session: Session, config: DefenseConfig = DefenseConfig.NONE) -> Experiment:
    row = Experiment(
        defense_config=config.value,
        model_id="test/model",
        injection_ratio=0.5,
        random_seed=1,
    )
    session.add(row)
    session.flush()
    return row


def _decision(
    session: Session,
    experiment: Experiment,
    *,
    attacked: bool,
    delta: float | None = 0.5,
    guard: bool | None = None,
    anomaly: bool | None = None,
    candidate: object = None,
    description: str = "tenant supplied description",
) -> Job:
    job = Job(
        description=description,
        is_synthetic_attack=attacked,
        attack_payload_type="direct_override" if attacked else None,
    )
    session.add(job)
    session.flush()
    entitlement = 0.0 if delta is None else 1.0
    allocation = 0.0 if delta is None else 1.0 + delta
    trace_id = uuid4()
    session.add(
        ScheduleDecision(
            experiment_id=experiment.experiment_id,
            job_id=job.job_id,
            trace_id=trace_id,
            guard_flagged=guard,
            anomaly_flagged=anomaly,
            llm_candidate=candidate,
            dominant_entitlement=entitlement,
            allocated_share=allocation,
        )
    )
    session.flush()
    return job


def _record(
    seed: int, config: DefenseConfig, experiment_id, *, asr: float | None
) -> ablation.RunRecord:
    return ablation.RunRecord(
        seed=seed,
        config=config,
        experiment_id=experiment_id,
        injected_jobs=2,
        jobs_failed=0,
        asr=asr,
        cfd=0.1 if asr is not None else None,
        mean_delta_injected=0.4 if asr is not None else None,
        guard_tpr=0.5 if asr is not None else None,
        guard_fpr=0.1 if asr is not None else None,
    )


class TestAblationArgumentsAndDatabaseHelpers:
    def test_parse_args_defaults_and_custom_options(self) -> None:
        defaults = ablation._parse_args([])
        assert defaults.backend == "echo"
        assert defaults.seeds == [0, 1, 2]
        assert defaults.seed == 0
        assert defaults.example is True

        custom = ablation._parse_args(
            ["--backend", "huggingface", "--model-id", "model/x", "--seeds", "4", "9",
             "--configs", "none", "full", "--ratio", "0.3", "--no-example"]
        )
        assert custom.backend == "huggingface"
        assert custom.seed == 4
        assert custom.seeds == [4, 9]
        assert custom.configs == ["none", "full"]
        assert custom.ratio == pytest.approx(0.3)
        assert custom.example is False

    def test_guard_rates_none_empty_and_mixed_populations(self, session: Session) -> None:
        empty = _experiment(session)
        assert ablation._guard_rates(session, empty.experiment_id) == (None, None)

        unguarded = _experiment(session)
        _decision(session, unguarded, attacked=True, guard=None)
        assert ablation._guard_rates(session, unguarded.experiment_id) == (None, None)

        mixed = _experiment(session, DefenseConfig.FULL)
        _decision(session, mixed, attacked=True, guard=True)
        _decision(session, mixed, attacked=True, guard=False)
        _decision(session, mixed, attacked=False, guard=False)
        assert ablation._guard_rates(session, mixed.experiment_id) == (0.5, 0.0)

        only_benign = _experiment(session, DefenseConfig.GUARD_ONLY)
        _decision(session, only_benign, attacked=False, guard=True)
        assert ablation._guard_rates(session, only_benign.experiment_id) == (None, 1.0)

    def test_job_latency_sums_stage_rows_per_trace(self, session: Session) -> None:
        experiment = _experiment(session)
        first = _decision(session, experiment, attacked=False)
        second = _decision(session, experiment, attacked=False)
        decisions = (
            session.query(ScheduleDecision)
            .filter_by(experiment_id=experiment.experiment_id)
            .all()
        )
        session.add_all(
            [
                StageLatency(trace_id=decisions[0].trace_id, stage="encode", latency_ms=2.5),
                StageLatency(trace_id=decisions[0].trace_id, stage="llm", latency_ms=7.5),
                StageLatency(trace_id=decisions[1].trace_id, stage="ilp", latency_ms=4.0),
            ]
        )
        session.flush()

        assert sorted(ablation._job_latencies_ms(session, experiment.experiment_id)) == [4.0, 10.0]
        assert first.job_id != second.job_id
        empty = _experiment(session, DefenseConfig.FULL)
        assert ablation._job_latencies_ms(session, empty.experiment_id) == []

    def test_record_success_and_missing_decisions_fallback(self, session: Session) -> None:
        populated = _experiment(session)
        _decision(session, populated, attacked=True, delta=0.5, guard=True)
        _decision(session, populated, attacked=False, delta=0.1, guard=False)
        record = ablation._record(
            session, seed=3, config=DefenseConfig.NONE, run_id=populated.experiment_id, failed=1
        )
        assert record.injected_jobs == 1
        assert record.asr == 1.0
        assert record.jobs_failed == 1
        assert record.guard_tpr == 1.0
        assert record.guard_fpr == 0.0

        empty = _experiment(session, DefenseConfig.FULL)
        fallback = ablation._record(
            session, seed=4, config=DefenseConfig.FULL, run_id=empty.experiment_id, failed=2
        )
        assert fallback.injected_jobs == 0
        assert fallback.jobs_failed == 2
        assert fallback.asr is None
        assert fallback.cfd is None


class TestAblationRendering:
    def test_cell_and_security_table_cover_values_and_missing_cells(self) -> None:
        assert ablation._cell([]) == "n/a"
        assert ablation._cell([0.25]) == "0.250"
        assert "+/-" in ablation._cell([0.2, 0.4])
        assert ablation._label(DefenseConfig.NONE) == "C0 none"

        records = [
            _record(0, DefenseConfig.NONE, uuid4(), asr=0.5),
            _record(1, DefenseConfig.NONE, uuid4(), asr=0.25),
            _record(0, DefenseConfig.FULL, uuid4(), asr=None),
        ]
        table = ablation.render_security_table(records, [DefenseConfig.NONE, DefenseConfig.FULL])
        assert "ASR@0.25" in table
        assert "C0 none" in table
        assert "C4 full" in table
        assert "n/a" in table

    def test_overhead_table_formats_percentiles_and_empty_lists(self) -> None:
        table = ablation.render_overhead_table(
            {DefenseConfig.NONE: [10.0, 20.0, 30.0], DefenseConfig.FULL: []},
            {DefenseConfig.NONE: 1, DefenseConfig.FULL: 2},
            [DefenseConfig.NONE, DefenseConfig.FULL],
        )
        assert "P50 ms/job" in table
        assert "20.0" in table
        assert "n/a" in table
        assert "2" in table

    def test_paired_table_handles_missing_baseline_pairs_and_valid_pairs(self) -> None:
        full = [_record(0, DefenseConfig.FULL, uuid4(), asr=0.2)]
        assert ablation.render_paired_table(full, [DefenseConfig.FULL]) is None
        baseline_only = [_record(0, DefenseConfig.NONE, uuid4(), asr=0.5)]
        assert ablation.render_paired_table(baseline_only, [DefenseConfig.NONE]) is None
        assert (
            ablation.render_paired_table(
                baseline_only, [DefenseConfig.NONE, DefenseConfig.FULL]
            )
            is None
        )

        records = [
            _record(0, DefenseConfig.NONE, uuid4(), asr=0.8),
            _record(1, DefenseConfig.NONE, uuid4(), asr=0.6),
            _record(0, DefenseConfig.FULL, uuid4(), asr=0.3),
            _record(1, DefenseConfig.FULL, uuid4(), asr=0.2),
            _record(2, DefenseConfig.FULL, uuid4(), asr=0.1),  # unmatched seed is ignored
        ]
        table = ablation.render_paired_table(records, [DefenseConfig.NONE, DefenseConfig.FULL])
        assert table is not None
        assert "ASR reduction" in table
        assert "C4 full" in table

    def test_proposal_shares_accepts_dict_json_and_missing_values(self) -> None:
        proposal = {
            "proposal": {
                "cpu_share": 0.1, "mem_share": 0.2, "disk_share": 0.3, "net_share": 0.4
            }
        }
        assert ablation._proposal_shares(proposal) == "0.10 0.20 0.30 0.40"
        assert ablation._proposal_shares(json.dumps(proposal)) == "0.10 0.20 0.30 0.40"
        assert ablation._proposal_shares({"proposal": {"cpu_share": 0.5}}) == "0.50 ? ? ?"
        assert ablation._proposal_shares(None) == "n/a"
        with pytest.raises(json.JSONDecodeError):
            ablation._proposal_shares("not-json")

    def test_worked_example_handles_empty_missing_and_present_jobs(self, session: Session) -> None:
        assert ablation.render_worked_example(session, [], seed=0) is None

        no_attack = _experiment(session)
        _decision(session, no_attack, attacked=False)
        assert ablation.render_worked_example(
            session, [_record(0, DefenseConfig.NONE, no_attack.experiment_id, asr=0.0)], seed=0
        ) is None

        missing_job_experiment = _experiment(session, DefenseConfig.NONE)
        _decision(session, missing_job_experiment, attacked=True)
        original_get = session.get
        session.get = lambda _model, _identity: None  # type: ignore[method-assign]
        assert ablation.render_worked_example(
            session,
            [_record(0, DefenseConfig.NONE, missing_job_experiment.experiment_id, asr=1.0)],
            seed=0,
        ) is None
        session.get = original_get  # type: ignore[method-assign]

        experiment = _experiment(session, DefenseConfig.NONE)
        long_description = "tenant text " * 15
        job = _decision(
            session,
            experiment,
            attacked=True,
            delta=0.8,
            guard=True,
            anomaly=False,
            candidate={"proposal": {"cpu_share": 0.1, "mem_share": 0.2}},
            description=long_description,
        )
        missing_experiment = _experiment(session, DefenseConfig.FULL)
        records = [
            _record(0, DefenseConfig.NONE, experiment.experiment_id, asr=1.0),
            _record(0, DefenseConfig.FULL, missing_experiment.experiment_id, asr=0.0),
        ]
        output = ablation.render_worked_example(session, records, seed=0)
        assert output is not None
        assert str(job.job_id)[:8] in output
        assert "FLAG" in output
        assert "pass" in output
        assert "0.10 0.20 ? ?" in output
        assert "job failed in pipeline" in output
        assert "guard: FLAG" in output


class TestAblationMain:
    def test_main_runs_reporting_path_with_controlled_persisted_rows(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        shared_jobs: dict[int, tuple[Job, Job]] = {}

        class Backend:
            model_id = "test/echo-fixture"

        def fake_sweep(session: Session, _runner, *, defense_config, seed, **_kwargs):
            experiment = _experiment(session, defense_config)
            if seed not in shared_jobs:
                attacked = Job(
                    description="controlled injected description",
                    is_synthetic_attack=True,
                    attack_payload_type="direct_override",
                )
                benign = Job(description="controlled benign description", is_synthetic_attack=False)
                session.add_all([attacked, benign])
                session.flush()
                shared_jobs[seed] = (attacked, benign)
            attacked, benign = shared_jobs[seed]
            for job, delta, flagged in ((attacked, 0.5, True), (benign, 0.1, False)):
                trace_id = uuid4()
                session.add(
                    ScheduleDecision(
                        experiment_id=experiment.experiment_id,
                        job_id=job.job_id,
                        trace_id=trace_id,
                        guard_flagged=flagged if defense_config.guard_active else None,
                        anomaly_flagged=flagged if defense_config.ilp_anomaly_active else None,
                        llm_candidate={"proposal": {"cpu_share": 0.4, "mem_share": 0.4}},
                        dominant_entitlement=1.0,
                        allocated_share=1.0 + delta,
                    )
                )
                session.add(StageLatency(trace_id=trace_id, stage="encode", latency_ms=3.0))
            session.flush()
            run = SimpleNamespace(experiment_id=experiment.experiment_id, jobs_failed=())
            return [SimpleNamespace(run=run)]

        monkeypatch.setattr(ablation, "_build_backend", lambda _args: Backend())
        monkeypatch.setattr(ablation, "run_injection_sweep", fake_sweep)
        database_url = f"sqlite:///{(tmp_path / 'main.db').as_posix()}"
        exit_code = ablation.main(
            [
                "--backend", "echo", "--num-jobs", "5", "--num-nodes", "3",
                "--seeds", "0", "1", "--configs", "none", "full", "--ratio", "0.4",
                "--database-url", database_url,
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "SMOKE TEST" in captured.out
        assert "SECURITY" in captured.out
        assert "OVERHEAD" in captured.out
        assert "DEFENSE EFFECT" in captured.out
        assert "WORKED EXAMPLE" in captured.out
        assert "P50 ms/job" in captured.out
        assert "[4/4]" in captured.err

    def test_main_returns_two_when_injection_runner_refuses(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class Backend:
            model_id = "test/backend"

        monkeypatch.setattr(ablation, "_build_backend", lambda _args: Backend())

        def refuse(*_args, **_kwargs):
            raise ablation.BaselineRunnerError("controlled refusal")

        monkeypatch.setattr(ablation, "run_injection_sweep", refuse)
        database_url = f"sqlite:///{(tmp_path / 'refused.db').as_posix()}"
        exit_code = ablation.main(
            ["--num-jobs", "5", "--num-nodes", "3", "--seeds", "0", "--configs", "none",
             "--database-url", database_url, "--no-example"]
        )
        assert exit_code == 2
        assert "ablation refused: controlled refusal" in capsys.readouterr().err

# Running

## Setup
    python -m venv venv
    venv\Scripts\activate            # Windows
    pip install -r requirements.txt
    copy .env.example .env           # then fill in HF token

## Smoke test (seconds, fake LLM, not a result)
    python -m eval.experiments.run_baseline_gate --backend echo --database-url sqlite:///./gate.db

## Tests
    pytest -m "not slow"

## Real baseline gate (GPU)
    python -m eval.experiments.run_baseline_gate --backend huggingface \
      --model-id Qwen/Qwen2.5-3B-Instruct \
      --duration-range 10 200 --deadline-range 200 2500 \
      --database-url sqlite:///./gate_run.db

Use a fresh `--database-url` for every run. ~9.5 s per job on an RTX 3050
(200 jobs ~ 32 min).

## Baseline calibration note
JCT is `critical_path / bottleneck_share`. With the default synthetic
durations (30-3600 s) the mean critical path alone is ~4500 s, so the
417.9 s reference is unreachable regardless of model. The gate is therefore
run with a duration/deadline scale matched to the reference. The pipeline and
model are not tuned. The un-calibrated default-parameter FAIL is reported too.

## Attack / ablation experiments
Use a fresh database per run (never the gate DB).

    python -m eval.experiments.run_ablation --backend echo --database-url sqlite:///./ablation_smoke.db

    python -m eval.experiments.run_ablation --backend huggingface \
      --model-id Qwen/Qwen2.5-3B-Instruct --num-jobs 60 --seeds 0 1 2 3 4 \
      --database-url sqlite:///./ablation_01.db

`--target-utilization` defaults to `ATTACK_EVAL_TARGET_UTILIZATION` (1.5, an
oversubscribed cluster). At <= 1.0 every job's DRF entitlement equals its demand
and the ILP never grants more than demand, so ASR is structurally 0. The
baseline gate keeps 0.766 so it stays comparable to the reference paper.


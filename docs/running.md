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
model are not tuned. The un-calibrated default-parameter FAIL is reported too.s
# Architecture

PromptGuard-Sched is a custom Python simulator (not CloudSim, which is Java)
that evaluates prompt injection against LLM-driven cloud schedulers.

## Pipeline (per job)

    [Guard]  ->  Encoder  ->  LLM  ->  [Anomaly check]  ->  ILP  ->  DB
     (C1,C4)    (trust      (proposes   (C3,C4: cap or      (CBC;     (schedule_
                 sep. C2,C4) shares)     reject)             feasible) decisions)

Brackets mark layers that run only for some `defense_config` values.

| Module | Role | Trust |
|---|---|---|
| `src/simulator/` | Jobs (task DAGs), cluster sizing, trace loading | system |
| `src/guard/` | Rule-based classifier; quarantines flagged tenant text | - |
| `src/encoder/` | Builds the prompt; separates system fields from tenant text | - |
| `src/llm/` | Backend (HuggingFace 4-bit / echo) and schema-checked proposal | untrusted output |
| `src/anomaly/` | Caps/rejects proposals whose Delta(J) exceeds a threshold | system |
| `src/ilp/` | Closest capacity-feasible allocation to the proposal (PuLP/CBC) | system |
| `src/scheduler/` | Pipeline orchestration, DRF entitlement, capacity ledger, persistence | system |
| `eval/` | Attacks, injection runner, metrics (ASR, CFD, Delta(J)), experiments | - |

## Key definitions

- **DRF entitlement**: a job's fair dominant share, computed as an LP
  (progressive filling) over the concurrently active jobs.
- **Delta(J)**: allocated dominant share minus DRF entitlement. Positive
  means over-allocation relative to fair share.
- **defense_config**: C0 none, C1 guard only, C2 trust separation only,
  C3 anomaly only, C4 full. Passed through every stage and stored per run.
- `guard_flagged` / `anomaly_flagged` are NULL when the layer did not run,
  so a query can distinguish "not flagged" from "layer inactive".
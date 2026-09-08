# PromptGuard-Sched

**Security evaluation of LLM-driven cloud resource scheduling: can tenant-controlled prompt injection manipulate scheduling decisions, and can a layered defense stop it — without breaking scheduling performance?**

[![Status](https://img.shields.io/badge/status-Phase%204%3A%20baseline%20pipeline%20wired-yellow)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-TBD-lightgrey)]()

---

## 1. What this project is

Recent scheduling research (LLMSched-style systems) proposes using an LLM to generate cloud resource-allocation decisions from a textual description of cluster state and job requirements. That textual description includes **tenant-controlled free-text fields** — job names, job descriptions, metadata — placed directly inside the LLM's context.

This project asks a specific, measurable question:

> **Can a tenant embed natural-language instructions inside those fields to manipulate the scheduler into over-allocating resources to their own job, and can a layered defense reduce that attack surface without unacceptable scheduling-performance or latency overhead?**

This is a **research system**, not a production scheduler and not a demo app. Every design decision here is subordinate to producing a reproducible, statistically sound answer to that question. See [`docs/PromptGuard-Sched_Final_Blueprint.md`](docs/PromptGuard-Sched_Final_Blueprint.md) for the full research plan — threat model, hypotheses, experimental matrix, and roadmap. **That document is the source of truth for scope and priorities; this README is the orientation layer on top of it.**

---

## 2. Core concepts (read this before touching code)

| Term | Meaning |
|---|---|
| `Δ(J)` (Delta-J) | `(allocated(J) - e_J) / e_J` — a job's allocation deviation from its DRF (Dominant Resource Fairness) entitlement `e_J`. The central metric of the whole project. |
| **ASR** | Attack Success Rate — fraction of injected jobs where `Δ(J) > τ_ASR` (default threshold `τ_ASR = 0.25`). |
| **CFD** | Collateral Fairness Deviation — `mean(|Δ(J)|)` over *non-injected* concurrent jobs. Measures blast radius on innocent tenants. |
| `defense_config` | One of `none / guard_only / trust_only / ilp_anomaly_only / full` (aka **C0–C4**). This is a **request parameter passed through the pipeline, never a code branch or an `if/else` fork in business logic.** Any new defense-related code must respect this. |
| `trace_id` | UUID attached to every job as it moves through the pipeline. Every stage logs its latency against this ID in `stage_latencies`. Do not compute latency any other way. |
| `model_id` | Recorded on every experiment and every LLM call. Results are **always** reported per-model. Never write or generate a claim like "the LLM is vulnerable" — it must be "Model X under config Y exhibited ASR Z." |

If you (human or agent) are about to add a feature and you can't say which of these five concepts it touches, stop and re-read the blueprint section it maps to.

---

## 3. Architecture

**Current phase: modular monolith.** One Python process, cleanly separated by module — **not** by network/service boundary. This is intentional (see blueprint §7 for the full rationale): baseline validation and the full experimental matrix must run correctly before any service-splitting is considered. Do not introduce microservices, message queues, or container orchestration unless the blueprint's Phase 9 gate has been explicitly reached.

```
Tenant Job Submission
   → Input Validation
   → Guard Classifier          (src/guard/)      — cheap first-pass detection, evadable by design
   → Trust-Aware State Encoder (src/encoder/)    — separates system-authored vs tenant-authored text
   → LLM Candidate Generation  (src/llm/)        — model_id always recorded
   → Statistical Anomaly Check (src/anomaly/)    — Δ(J) vs DRF entitlement — PRIMARY SECURITY BOUNDARY
   → ILP Refinement            (src/ilp/)        — PuLP/CBC, finalizes allocation
   → Execution Controller      (src/scheduler/)
   → Metrics / DB              (db/, eval/metrics/)
```

Each stage is independently switchable via `defense_config` — this is what makes the C0–C4 ablation experiment (blueprint §12) a single reproducible run instead of five hand-edited scripts.

---

## 4. Repository structure

```
promptguard-sched/
├── src/
│   ├── simulator/     # Google cluster trace loader, job/task/DAG representation
│   ├── encoder/       # trust-aware structured state encoding (system vs tenant text)
│   ├── llm/           # model backend wrapper(s); defense_config-aware
│   ├── ilp/           # PuLP/CBC-based allocation refinement
│   ├── guard/         # Layer 1 defense — cheap classifier/heuristics
│   ├── anomaly/       # Layer 3 defense — Δ(J)/DRF statistical boundary
│   └── scheduler/     # pipeline orchestration, execution controller
├── eval/
│   ├── attacks/       # versioned payload library (6 attack families, see blueprint §6)
│   ├── experiments/   # experiment runner — sweeps ratio × threshold × model × defense_config × seed
│   ├── metrics/       # ASR, CFD, Δ(J), latency computation
│   ├── statistics/    # confidence intervals, paired significance tests, effect sizes
│   └── plots/         # figure generation for the paper (reads from DB, not from hand-copied numbers)
├── db/
│   └── migrations/    # Alembic migrations — schema in blueprint §9
├── tests/
│   ├── unit/                    # esp. Δ(J)/DRF entitlement correctness
│   ├── integration/             # full pipeline, trace_id linkage across stages
│   └── adversarial_regression/  # re-runs payload library on every guard/LLM/anomaly change
├── frontend/           # dashboard (built only after Phase 6 results are stable — not yet started)
├── data/               # Google cluster trace subset (gitignored — see §6)
├── docs/
│   └── PromptGuard-Sched_Final_Blueprint.md   # full research plan — READ THIS FIRST
├── configs/            # experiment config files (injection ratios, thresholds, model lists)
├── requirements.txt
├── pyproject.toml
└── .env.example
```

**Current implementation status:** `simulator/`, `encoder/`, `llm/` (backend + candidate-generation client), `ilp/` (PuLP/CBC refinement), and `scheduler/` (orchestrator + DRF fairness + persistence) are implemented, wired end-to-end for `defense_config=none`. `guard/` and `anomaly/` are not implemented yet (blueprint §16 phases 7-8) — the orchestrator does not call them and records `guard_flagged`/`anomaly_flagged` as `NULL`, not `False`, so that distinction survives in the DB. No experiments have been run against the trace dataset yet; the baseline validation gate (blueprint §13) has **not** been passed. **Do not build attack, defense, or dashboard code before that gate passes** — this is a hard project rule, not a suggestion.

---

## 5. Environment

| | |
|---|---|
| Python | 3.11+ (pinned via `pyenv local`) — **not** the system Python, which lacks PyTorch wheel support on this dev machine |
| GPU | RTX 3050 6GB (laptop) — models must run 4-bit quantized (`bitsandbytes`); do not assume full-precision 7B+ models fit |
| DB | SQLite for early development; schema is Postgres-compatible for later migration (blueprint §9 uses a `GENERATED ALWAYS AS ... STORED` column — supported in SQLite ≥ 3.31 and Postgres) |
| Dataset | Google cluster-usage trace (2011) — start with a 1–2 day subset, not the full 29-day trace |

### Setup

```bash
pyenv install 3.11.9
pyenv virtualenv 3.11.9 promptguard
pyenv local promptguard

pip install -r requirements.txt
cp .env.example .env   # fill in HF_TOKEN and DATABASE_URL
```

Verify GPU is visible:
```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## 6. What NOT to do (explicit, because agents/collaborators default to these)

- **Do not** introduce microservices, Docker Compose service topologies, Celery, or Kubernetes config. That is explicitly deferred to an optional later phase (blueprint §7.2) and only if justified.
- **Do not** hardcode `model_id`, `defense_config`, or thresholds inside business logic — these are always parameters, sourced from `configs/` or experiment specs, never magic strings buried in a function.
- **Do not** compute ASR/CFD/latency by hand or in a notebook and paste numbers into the paper/README. They must come from a `SELECT` against `schedule_decisions` / `stage_latencies` — that reproducibility guarantee is the single most important property of this codebase.
- **Do not** commit the dataset, model weights, `.env`, or any `.db` file — see `.gitignore`.
- **Do not** build the frontend dashboard, add authentication, or add deployment config before the baseline gate (§13 of the blueprint) has passed with results.
- **Do not** claim "the LLM is vulnerable" anywhere in code comments, logs, or docs — always model-scoped claims (§2 above).

---

## 7. Code standards

- Type hints on all function signatures.
- Dataclasses (or Pydantic models where request/response validation is needed) for structured data — no bare dicts passed between pipeline stages.
- Named constants for thresholds/ratios (`TAU_ASR_DEFAULT = 0.25`, not a bare `0.25` in code) — defined in `configs/` or a `constants.py`, not scattered.
- Every pipeline stage function takes and returns typed objects carrying `trace_id` and `defense_config` — do not silently drop them.
- Tests required for: `Δ(J)`/DRF entitlement calculation, ILP constraint construction, and any new attack payload category.

---

## 8. Where to start

1. Read `docs/PromptGuard-Sched_Final_Blueprint.md` in full — sections 1, 5–9, and 13 especially.
2. Implement `src/simulator/` — trace loader + job/task/DAG model. No LLM calls yet.
3. Implement `src/encoder/` — converts simulator output into the structured textual state the LLM will consume, with system-authored and tenant-authored fields kept explicitly separate (this separation is Defense Layer 2 — build it in from the start, don't retrofit it).
4. Implement `db/migrations/` from the schema in blueprint §9.
5. Implement `src/llm/` and `src/ilp/`, wire them into `src/scheduler/` with `defense_config="none"`.
6. Run the baseline, compare against LLMSched reference numbers (blueprint §11) — **this is the gate.** Nothing past this point starts until it passes.

---

## 9. Reference

Full research plan, threat model, formal metrics, experimental matrix, defense architecture, 12-week roadmap, paper structure, and acceptance criteria: [`docs/PromptGuard-Sched_Final_Blueprint.md`](docs/PromptGuard-Sched_Final_Blueprint.md).
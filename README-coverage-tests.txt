PromptGuard-Sched: coverage tests only
=====================================

Contents
--------
- tests/unit/test_benign_control.py
- tests/unit/test_run_ablation_reporting.py

These are test-only additions. The archive does not modify production code,
README.md, pyproject.toml, or the configured 85% coverage threshold.

Install
-------
1. Extract this ZIP into the root of your existing PromptGuard-Sched project.
   The archive preserves the tests/unit/ directory structure.
2. From the project root, run the focused tests:

   python -m pytest tests/unit/test_benign_control.py tests/unit/test_run_ablation_reporting.py -v -o addopts=""

3. If those pass, run the full project suite with coverage:

   python -m pytest

The ablation CLI tests use controlled, mocked persisted rows; they do not load
or call a real LLM and do not require a GPU. Existing project dependencies
must already be installed, including PuLP because run_ablation imports the
ILP implementation.

Expected focused result: 14 passed.
Coverage of the two target modules in the package author's isolated run:
- eval/experiments/benign_control.py: 96%
- eval/experiments/run_ablation.py: 98%
- combined target-module coverage: 97.22%

These are isolated test-run measurements, not a guarantee of the final
whole-project coverage percentage. The full suite is the authoritative check.

"""Trace loading for PromptGuard-Sched.

Two sources of `Job` objects, both returning the same `list[Job]` contract
so nothing downstream needs to know which one produced them:

1. `GoogleClusterTraceLoader` — parses a *preprocessed* Google cluster-usage
   trace CSV (blueprint §11). The raw Borg/Google trace ships as several
   gzipped CSV families (job_events, task_events, task_usage) joined on
   `job_id`/`task_index`; reconstructing that join is a data-engineering
   step outside this module's scope. This loader expects one flat,
   already-joined CSV with the columns in `PREPROCESSED_TRACE_SCHEMA` below.
   Document the join script that produces it in `eval/experiments/` once
   that module exists.

2. `SyntheticTraceGenerator` — a seeded, deterministic generator producing
   valid `Job` DAGs. This is what Phase 0–2 development and unit tests run
   against before the real trace subset is wired in (blueprint §16, Week 2).
   It correctly sets `is_synthetic_attack` / `attack_payload_type` ground
   truth for the injection-ratio axis (1%/5%/10%, blueprint §12), but it
   does NOT generate real attack payload text — that is eval/attacks/'s job.
   By default it writes a clearly-labeled placeholder string; pass an
   `attack_payload_injector` callback to plug in real payloads once
   eval/attacks/ exists.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd

from src.simulator.models import AttackFamily, Job, ResourceDemand, Task, TaskEdge

# --- Google cluster trace (preprocessed CSV) --------------------------------

# Required columns in the flat, pre-joined CSV this loader consumes.
# One row per task; job-level fields (priority, deadline_s, weight,
# description, tenant_id) are expected to be repeated on every row of that
# job's tasks and are asserted equal across the group.
PREPROCESSED_TRACE_SCHEMA: tuple[str, ...] = (
    "job_id",
    "tenant_id",
    "task_index",
    "task_name",
    "cpu_demand",
    "mem_demand_gb",
    "disk_demand_gb",
    "net_demand_mbps",
    "est_duration_s",
    "priority",
    "deadline_s",
    "weight",
    "description",
    "parent_task_index",  # empty/NaN for tasks with no predecessor
    "data_transfer_gb",  # ignored when parent_task_index is empty
)

PRIORITY_LEVELS: int = 12  # blueprint §11: "12 priority levels"


class TraceFormatError(ValueError):
    """Raised when a trace file doesn't satisfy `PREPROCESSED_TRACE_SCHEMA`."""


class GoogleClusterTraceLoader:
    """Loads a preprocessed Google cluster-usage trace CSV into `Job` objects."""

    def __init__(self, trace_path: Path | str) -> None:
        self._trace_path = Path(trace_path)

    def load(self) -> list[Job]:
        """Parse the CSV and return one `Job` per distinct `job_id`.

        Raises:
            TraceFormatError: required columns are missing, or a job's rows
                disagree on a field that must be job-level (e.g. two rows
                for the same `job_id` with different `priority`).
        """
        if not self._trace_path.exists():
            raise TraceFormatError(f"trace file not found: {self._trace_path}")

        frame = pd.read_csv(self._trace_path)
        missing = set(PREPROCESSED_TRACE_SCHEMA) - set(frame.columns)
        if missing:
            raise TraceFormatError(f"trace CSV missing required columns: {sorted(missing)}")

        return [self._build_job(job_id, group) for job_id, group in frame.groupby("job_id")]

    @staticmethod
    def _build_job(job_id: object, group: pd.DataFrame) -> Job:
        job_level_fields = ("tenant_id", "priority", "deadline_s", "weight", "description")
        for field in job_level_fields:
            if group[field].nunique(dropna=False) > 1:
                raise TraceFormatError(
                    f"job_id={job_id!r} has inconsistent values for job-level field {field!r}"
                )

        first = group.iloc[0]
        index_to_task_id: dict[int, UUID] = {
            int(row.task_index): uuid4() for _, row in group.iterrows()
        }

        tasks = tuple(
            Task(
                task_id=index_to_task_id[int(row.task_index)],
                task_name=str(row.task_name),
                demand=ResourceDemand(
                    cpu=float(row.cpu_demand),
                    mem_gb=float(row.mem_demand_gb),
                    disk_gb=float(row.disk_demand_gb),
                    net_mbps=float(row.net_demand_mbps),
                ),
                est_duration_s=int(row.est_duration_s),
            )
            for _, row in group.iterrows()
        )

        edges = tuple(
            TaskEdge(
                parent_task_id=index_to_task_id[int(row.parent_task_index)],
                child_task_id=index_to_task_id[int(row.task_index)],
                data_transfer_gb=float(row.data_transfer_gb),
            )
            for _, row in group.iterrows()
            if pd.notna(row.parent_task_index)
        )

        deadline_s = None if pd.isna(first.deadline_s) else int(first.deadline_s)
        return Job(
            tenant_id=UUID(str(first.tenant_id)),
            priority=int(first.priority),
            deadline_s=deadline_s,
            weight=float(first.weight),
            description=str(first.description),
            tasks=tasks,
            edges=edges,
        )


# --- Synthetic generator -----------------------------------------------------

DEFAULT_CPU_RANGE: tuple[float, float] = (0.5, 8.0)
DEFAULT_MEM_RANGE_GB: tuple[float, float] = (0.5, 32.0)
DEFAULT_DISK_RANGE_GB: tuple[float, float] = (1.0, 100.0)
DEFAULT_NET_RANGE_MBPS: tuple[float, float] = (10.0, 1000.0)
DEFAULT_DURATION_RANGE_S: tuple[int, int] = (30, 3600)
DEFAULT_TRANSFER_RANGE_GB: tuple[float, float] = (0.1, 10.0)

# Placeholder marker for attack-labeled jobs when no real payload injector is
# supplied. Deliberately inert text — never mistake this for an actual
# attack payload from eval/attacks/.
_PLACEHOLDER_ATTACK_MARKER = "[SYNTHETIC ATTACK PLACEHOLDER — no payload text injected]"

AttackPayloadInjector = Callable[[str, AttackFamily], str]


class SyntheticTraceGenerator:
    """Deterministic, seeded generator of valid `Job` DAGs for pre-trace development."""

    def __init__(self, seed: int, num_tenants: int = 10) -> None:
        if num_tenants < 1:
            raise ValueError("num_tenants must be >= 1")
        self._rng = random.Random(seed)
        self._tenant_ids: tuple[UUID, ...] = tuple(uuid4() for _ in range(num_tenants))

    def generate(
        self,
        num_jobs: int,
        tasks_per_job: tuple[int, int] = (1, 5),
        injection_ratio: float = 0.0,
        attack_payload_injector: AttackPayloadInjector | None = None,
    ) -> list[Job]:
        """Generate `num_jobs` synthetic jobs.

        Args:
            num_jobs: number of jobs to produce.
            tasks_per_job: inclusive (min, max) task count per job's DAG.
            injection_ratio: fraction of jobs (0.0–1.0) labeled as synthetic
                attacks. Matches the 1%/5%/10% axis in blueprint §12.
            attack_payload_injector: optional callback `(description,
                attack_family) -> description` to write real attack text
                into an attack-labeled job's description. Defaults to a
                clearly-marked placeholder — wire this to eval/attacks/'s
                payload library once it exists.
        """
        if num_jobs < 1:
            raise ValueError("num_jobs must be >= 1")
        min_tasks, max_tasks = tasks_per_job
        if min_tasks < 1 or max_tasks < min_tasks:
            raise ValueError("tasks_per_job must satisfy 1 <= min <= max")
        if not 0.0 <= injection_ratio <= 1.0:
            raise ValueError("injection_ratio must be in [0.0, 1.0]")

        num_attack_jobs = round(num_jobs * injection_ratio)
        attack_flags = [True] * num_attack_jobs + [False] * (num_jobs - num_attack_jobs)
        self._rng.shuffle(attack_flags)

        return [
            self._generate_job(is_attack, min_tasks, max_tasks, attack_payload_injector)
            for is_attack in attack_flags
        ]

    def _generate_job(
        self,
        is_attack: bool,
        min_tasks: int,
        max_tasks: int,
        attack_payload_injector: AttackPayloadInjector | None,
    ) -> Job:
        num_tasks = self._rng.randint(min_tasks, max_tasks)
        tasks = tuple(self._random_task(index) for index in range(num_tasks))
        edges = self._random_dag_edges(tasks)

        description = "synthetic benign job"
        attack_payload_type: AttackFamily | None = None
        if is_attack:
            attack_payload_type = self._rng.choice(list(AttackFamily))
            description = (
                attack_payload_injector(description, attack_payload_type)
                if attack_payload_injector is not None
                else f"{description} {_PLACEHOLDER_ATTACK_MARKER}"
            )

        return Job(
            tenant_id=self._rng.choice(self._tenant_ids),
            priority=self._rng.randint(0, PRIORITY_LEVELS - 1),
            deadline_s=self._rng.choice([None, self._rng.randint(60, 7200)]),
            weight=round(self._rng.uniform(0.1, 10.0), 3),
            description=description,
            tasks=tasks,
            edges=edges,
            is_synthetic_attack=is_attack,
            attack_payload_type=attack_payload_type,
        )

    def _random_task(self, index: int) -> Task:
        return Task(
            task_name=f"synthetic-task-{index}",
            demand=ResourceDemand(
                cpu=round(self._rng.uniform(*DEFAULT_CPU_RANGE), 2),
                mem_gb=round(self._rng.uniform(*DEFAULT_MEM_RANGE_GB), 2),
                disk_gb=round(self._rng.uniform(*DEFAULT_DISK_RANGE_GB), 2),
                net_mbps=round(self._rng.uniform(*DEFAULT_NET_RANGE_MBPS), 2),
            ),
            est_duration_s=self._rng.randint(*DEFAULT_DURATION_RANGE_S),
        )

    def _random_dag_edges(self, tasks: Sequence[Task]) -> tuple[TaskEdge, ...]:
        """Build a random-but-valid DAG: every edge goes from a lower to a
        higher task index, which makes acyclicity trivially guaranteed
        rather than something to detect after the fact.
        """
        if len(tasks) < 2:
            return ()

        edges: list[TaskEdge] = []
        for child_index in range(1, len(tasks)):
            # Every task after the first depends on at least one earlier
            # task, so the DAG is always weakly connected.
            parent_index = self._rng.randint(0, child_index - 1)
            edges.append(self._make_edge(tasks[parent_index], tasks[child_index]))

            # Occasionally add one extra predecessor for a denser DAG.
            if child_index > 1 and self._rng.random() < 0.2:
                extra_parent_index = self._rng.randint(0, child_index - 1)
                if extra_parent_index != parent_index:
                    edges.append(self._make_edge(tasks[extra_parent_index], tasks[child_index]))

        return tuple(edges)

    def _make_edge(self, parent: Task, child: Task) -> TaskEdge:
        return TaskEdge(
            parent_task_id=parent.task_id,
            child_task_id=child.task_id,
            data_transfer_gb=round(self._rng.uniform(*DEFAULT_TRANSFER_RANGE_GB), 2),
        )
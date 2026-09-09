"""initial schema

Creates every table in blueprint §9's database design, column-for-column
and constraint-for-constraint against `db/migrations/models.py` — that
module's own docstring is explicit that it is the single source of truth
this migration must track, not the other way around. Written by hand
rather than via `alembic revision --autogenerate` (no live DB in this
environment to diff against), but it mirrors `Base.metadata` exactly so a
future `--autogenerate` run against a database built from this revision
should produce an empty diff.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-09 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from db.migrations.models import GUID, PortableJSON
from src.config import DefenseConfig, PipelineStage
from src.simulator.models import AttackFamily

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", GUID(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("job_id", GUID(), primary_key=True),
        sa.Column(
            "tenant_id", GUID(), sa.ForeignKey("tenants.tenant_id"), nullable=True
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("priority", sa.SmallInteger(), nullable=True),
        sa.Column("deadline_s", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Numeric(), nullable=True),
        # Attack surface (blueprint §5) — tenant-authored free text.
        sa.Column("description", sa.String(4096), nullable=False),
        # Ground truth for ASR/CFD. Never read upstream of eval/metrics/.
        sa.Column("is_synthetic_attack", sa.Boolean(), nullable=False),
        sa.Column("attack_payload_type", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "attack_payload_type IS NULL OR attack_payload_type IN ("
            + ", ".join(f"'{family.value}'" for family in AttackFamily)
            + ")",
            name="ck_jobs_attack_payload_type_valid",
        ),
        sa.CheckConstraint(
            "(attack_payload_type IS NULL) OR is_synthetic_attack",
            name="ck_jobs_attack_label_consistency",
        ),
    )
    op.create_index("idx_jobs_attack_label", "jobs", ["is_synthetic_attack", "attack_payload_type"])

    op.create_table(
        "tasks",
        sa.Column("task_id", GUID(), primary_key=True),
        sa.Column("job_id", GUID(), sa.ForeignKey("jobs.job_id"), nullable=False),
        # Also an attack-surface field (blueprint §6) — tenant-authored.
        sa.Column("task_name", sa.String(512), nullable=False),
        sa.Column("cpu_demand", sa.Numeric(), nullable=False),
        sa.Column("mem_demand_gb", sa.Numeric(), nullable=False),
        sa.Column("disk_demand", sa.Numeric(), nullable=False),
        sa.Column("net_demand", sa.Numeric(), nullable=False),
        sa.Column("est_duration_s", sa.Integer(), nullable=False),
    )
    op.create_index("idx_tasks_job_id", "tasks", ["job_id"])

    op.create_table(
        "task_edges",
        sa.Column(
            "parent_task_id", GUID(), sa.ForeignKey("tasks.task_id"), primary_key=True
        ),
        sa.Column(
            "child_task_id", GUID(), sa.ForeignKey("tasks.task_id"), primary_key=True
        ),
        sa.Column("data_transfer_gb", sa.Numeric(), nullable=False),
        sa.CheckConstraint("parent_task_id <> child_task_id", name="ck_task_edges_no_self_loop"),
    )

    op.create_table(
        "nodes",
        sa.Column("node_id", GUID(), primary_key=True),
        sa.Column("zone", sa.String(64), nullable=False),
        sa.Column("cpu_capacity", sa.Numeric(), nullable=False),
        sa.Column("mem_capacity_gb", sa.Numeric(), nullable=False),
        sa.Column("disk_capacity", sa.Numeric(), nullable=False),
        sa.Column("net_capacity", sa.Numeric(), nullable=False),
    )

    op.create_table(
        "experiments",
        sa.Column("experiment_id", GUID(), primary_key=True),
        # Stored as the enum's value (str) — DefenseConfig (src/config.py)
        # is the single source of truth, never a bare hardcoded string.
        sa.Column("defense_config", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("injection_ratio", sa.Numeric(), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "defense_config IN (" + ", ".join(f"'{cfg.value}'" for cfg in DefenseConfig) + ")",
            name="ck_experiments_defense_config_valid",
        ),
    )

    op.create_table(
        "schedule_decisions",
        sa.Column("decision_id", GUID(), primary_key=True),
        sa.Column(
            "experiment_id",
            GUID(),
            sa.ForeignKey("experiments.experiment_id"),
            nullable=False,
        ),
        sa.Column("job_id", GUID(), sa.ForeignKey("jobs.job_id"), nullable=False),
        # Threaded through every pipeline stage (blueprint §8 rule #2) —
        # every row in stage_latencies with this trace_id is one job's
        # full timing breakdown, joinable with zero extra instrumentation.
        sa.Column("trace_id", GUID(), nullable=False),
        sa.Column("guard_flagged", sa.Boolean(), nullable=True),
        sa.Column("guard_score", sa.Numeric(), nullable=True),
        sa.Column("llm_candidate", PortableJSON(), nullable=True),
        sa.Column("ilp_allocation", PortableJSON(), nullable=True),
        sa.Column("anomaly_flagged", sa.Boolean(), nullable=True),
        sa.Column("dominant_entitlement", sa.Numeric(), nullable=False),
        sa.Column("allocated_share", sa.Numeric(), nullable=False),
        # Generated column: the DB computes Δ(J), application code never
        # does. NULLIF guards the zero-entitlement edge case in every
        # dialect (see db/migrations/models.py ScheduleDecision docstring).
        sa.Column(
            "delta_j",
            sa.Numeric(),
            sa.Computed(
                "(allocated_share - dominant_entitlement) / NULLIF(dominant_entitlement, 0)",
                persisted=True,
            ),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_schedule_experiment", "schedule_decisions", ["experiment_id"])
    op.create_index("idx_schedule_delta", "schedule_decisions", ["delta_j"])
    op.create_index("idx_schedule_trace", "schedule_decisions", ["trace_id"])

    op.create_table(
        "stage_latencies",
        sa.Column("trace_id", GUID(), primary_key=True),
        sa.Column("stage", sa.String(32), primary_key=True),
        sa.Column("latency_ms", sa.Numeric(), nullable=False),
        sa.CheckConstraint(
            "stage IN (" + ", ".join(f"'{stage.value}'" for stage in PipelineStage) + ")",
            name="ck_stage_latencies_stage_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("stage_latencies")
    op.drop_index("idx_schedule_trace", table_name="schedule_decisions")
    op.drop_index("idx_schedule_delta", table_name="schedule_decisions")
    op.drop_index("idx_schedule_experiment", table_name="schedule_decisions")
    op.drop_table("schedule_decisions")
    op.drop_table("experiments")
    op.drop_table("nodes")
    op.drop_table("task_edges")
    op.drop_index("idx_tasks_job_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("idx_jobs_attack_label", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("tenants")

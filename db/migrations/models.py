"""SQLAlchemy ORM models — the persisted form of blueprint §9's schema.

Why this file is load-bearing (README §6): ASR, CFD, and latency numbers
must come from a `SELECT` against `schedule_decisions` / `stage_latencies`,
never from a notebook or a hand-copied number. That guarantee only holds if
these models exactly match §9 — column-for-column, index-for-index. If you
need a new derived metric, add a query in `eval/metrics/`, not a new column
here computed in Python and never persisted.

Two cross-dialect concerns this module solves once, centrally, so no other
module has to think about them:

1. **UUID storage.** Postgres has a native `UUID` type; SQLite (the dev DB
   per README §5) does not. `GUID` below stores a `CHAR(32)` hex string on
   SQLite and a native `UUID` on Postgres, while every Python-facing
   attribute is a real `uuid.UUID` either way.
2. **JSON storage.** Postgres gets `JSONB` (indexable, binary); SQLite gets
   the generic `JSON` type. `PortableJSON` picks the right one per dialect.

`delta_j` is a SQLAlchemy `Computed` column — the database computes it, not
application code — which is what makes "ASR = COUNT(*) WHERE delta_j > τ"
a query anyone can run against the raw table, not something that depends on
re-deriving Δ(J) correctly in every consumer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    TypeDecorator,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, CHAR

from src.config import DefenseConfig, PipelineStage
from src.simulator.models import AttackFamily


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID: native `UUID` on Postgres, `CHAR(32)` hex
    (no dashes) on everything else (SQLite, per README §5's dev DB).

    Modeled on the pattern in the SQLAlchemy docs for exactly this problem —
    kept here rather than per-column so every table gets identical UUID
    semantics without repeating the dialect branch six times.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(value)
        return value.hex

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


def PortableJSON() -> JSON:  # noqa: N802 — factory mimics a type constructor
    """`JSONB` on Postgres (indexable, binary-stored), plain `JSON` on SQLite.

    Used for `schedule_decisions.llm_candidate` / `.ilp_allocation` — kept
    as JSON rather than normalized columns deliberately (blueprint §9: "raw
    LLM output, kept for audit"). Normalizing it would let the audit trail
    drift from what the model/solver actually produced.
    """
    return JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Shared declarative base for every table in this module."""


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    jobs: Mapped[list[Job]] = relationship(back_populates="tenant")


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tenants.tenant_id"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    priority: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
    deadline_s: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    weight: Mapped[float | None] = mapped_column(Numeric(), nullable=True)

    # --- Attack surface (blueprint §5) — tenant-authored free text ---------
    description: Mapped[str] = mapped_column(String(4096), nullable=False, default="")

    # --- Ground truth for ASR/CFD. Never read upstream of eval/metrics/. ---
    is_synthetic_attack: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    attack_payload_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tenant: Mapped[Tenant | None] = relationship(back_populates="jobs")
    tasks: Mapped[list[Task]] = relationship(back_populates="job", cascade="all, delete-orphan")
    schedule_decisions: Mapped[list[ScheduleDecision]] = relationship(back_populates="job")

    __table_args__ = (
        Index("idx_jobs_attack_label", "is_synthetic_attack", "attack_payload_type"),
        CheckConstraint(
            "attack_payload_type IS NULL OR attack_payload_type IN ("
            + ", ".join(f"'{family.value}'" for family in AttackFamily)
            + ")",
            name="ck_jobs_attack_payload_type_valid",
        ),
        CheckConstraint(
            "(attack_payload_type IS NULL) OR is_synthetic_attack",
            name="ck_jobs_attack_label_consistency",
        ),
    )


class Task(Base):
    __tablename__ = "tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.job_id"), nullable=False)

    # Also an attack-surface field (blueprint §6) — tenant-authored.
    task_name: Mapped[str] = mapped_column(String(512), nullable=False)

    cpu_demand: Mapped[float] = mapped_column(Numeric(), nullable=False)
    mem_demand_gb: Mapped[float] = mapped_column(Numeric(), nullable=False)
    disk_demand: Mapped[float] = mapped_column(Numeric(), nullable=False)
    net_demand: Mapped[float] = mapped_column(Numeric(), nullable=False)
    est_duration_s: Mapped[int] = mapped_column(Integer(), nullable=False)

    job: Mapped[Job] = relationship(back_populates="tasks")

    __table_args__ = (Index("idx_tasks_job_id", "job_id"),)


class TaskEdge(Base):
    __tablename__ = "task_edges"

    parent_task_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tasks.task_id"), primary_key=True
    )
    child_task_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tasks.task_id"), primary_key=True
    )
    data_transfer_gb: Mapped[float] = mapped_column(Numeric(), nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("parent_task_id <> child_task_id", name="ck_task_edges_no_self_loop"),
    )


class Node(Base):
    __tablename__ = "nodes"

    node_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    zone: Mapped[str] = mapped_column(String(64), nullable=False)
    cpu_capacity: Mapped[float] = mapped_column(Numeric(), nullable=False)
    mem_capacity_gb: Mapped[float] = mapped_column(Numeric(), nullable=False)
    disk_capacity: Mapped[float] = mapped_column(Numeric(), nullable=False)
    net_capacity: Mapped[float] = mapped_column(Numeric(), nullable=False)


class Experiment(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    # Stored as the enum's value (str), never a bare hardcoded string —
    # DefenseConfig is the single source of truth (src/config.py).
    defense_config: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    injection_ratio: Mapped[float] = mapped_column(Numeric(), nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer(), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    schedule_decisions: Mapped[list[ScheduleDecision]] = relationship(
        back_populates="experiment"
    )

    __table_args__ = (
        CheckConstraint(
            "defense_config IN ("
            + ", ".join(f"'{cfg.value}'" for cfg in DefenseConfig)
            + ")",
            name="ck_experiments_defense_config_valid",
        ),
    )


class ScheduleDecision(Base):
    __tablename__ = "schedule_decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("experiments.experiment_id"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.job_id"), nullable=False)
    # Threaded through every pipeline stage (blueprint §8 rule #2) — every
    # row in stage_latencies with this trace_id is one job's full timing
    # breakdown, joinable with zero extra instrumentation.
    trace_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    guard_flagged: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    guard_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    llm_candidate: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON(), nullable=True)
    ilp_allocation: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON(), nullable=True)
    anomaly_flagged: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)

    dominant_entitlement: Mapped[float] = mapped_column(Numeric(), nullable=False)
    allocated_share: Mapped[float] = mapped_column(Numeric(), nullable=False)

    # Generated column: the DB computes Δ(J), application code never does.
    # NULLIF guards the same zero-entitlement edge case in every dialect.
    delta_j: Mapped[float] = mapped_column(
        Numeric(),
        Computed(
            "(allocated_share - dominant_entitlement) / NULLIF(dominant_entitlement, 0)",
            persisted=True,
        ),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    experiment: Mapped[Experiment] = relationship(back_populates="schedule_decisions")
    job: Mapped[Job] = relationship(back_populates="schedule_decisions")

    __table_args__ = (
        Index("idx_schedule_experiment", "experiment_id"),
        Index("idx_schedule_delta", "delta_j"),
        Index("idx_schedule_trace", "trace_id"),
    )


class StageLatency(Base):
    __tablename__ = "stage_latencies"

    trace_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), primary_key=True)
    latency_ms: Mapped[float] = mapped_column(Numeric(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "stage IN (" + ", ".join(f"'{stage.value}'" for stage in PipelineStage) + ")",
            name="ck_stage_latencies_stage_valid",
        ),
    )
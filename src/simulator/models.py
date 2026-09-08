"""Job/task data models.

These are the pipeline's canonical data contracts (blueprint §8, README rule:
"no bare dicts between pipeline stages"). Every downstream module — encoder,
LLM wrapper, ILP refiner, guard, anomaly checker — consumes and produces
these models, never raw dicts.

Two things matter more than anything else here:

1. Trust boundary. `Job.description` and `Task.task_name` are the attack
   surface (blueprint §5/§6) — free text a tenant controls. Every other
   field is system-authored (measured or assigned, never tenant-supplied
   text). Keeping that split explicit in the model, not just in a comment
   somewhere else, is what makes the encoder's trust-aware separation
   possible later.
2. `is_synthetic_attack` / `attack_payload_type` are ground-truth labels for
   ASR computation, not features the scheduler is allowed to see. They must
   never be read anywhere upstream of `eval/metrics/`.
"""

from __future__ import annotations

from enum import Enum
from uuid import UUID, uuid4

import networkx as nx
from pydantic import BaseModel, Field, model_validator

# Resource demand bounds. A demand of exactly zero is nonsensical for a task
# that consumes that resource at all — better to catch it here than let a
# zero-division ripple into a DRF calculation three modules downstream.
MIN_RESOURCE_DEMAND: float = 0.0
MIN_DURATION_S: int = 1


class AttackFamily(str, Enum):
    """The six attack families from blueprint §6.

    Kept here (not only in eval/attacks/) because `Job.attack_payload_type`
    needs a closed, validated vocabulary — a typo'd label silently breaking
    a `GROUP BY attack_payload_type` in the stats layer is the kind of bug
    that doesn't show up until the paper's numbers don't add up.
    """

    DIRECT_OVERRIDE = "direct_override"
    ROLE_CONFUSION = "role_confusion"
    SYSTEM_TAG_SPOOFING = "system_tag_spoofing"
    URGENCY_AUTHORITY_FRAMING = "urgency_authority_framing"
    INDIRECT_INSTRUCTION = "indirect_instruction"
    OBFUSCATED_VARIANT = "obfuscated_variant"


class ResourceDemand(BaseModel):
    """A resource vector shared by both task demands and node capacities.

    Using one model for both demand and capacity (rather than two near-
    identical classes) means `dominant_resource_share` in
    `src/scheduler/fairness.py` can operate on either without conversion.
    """

    model_config = {"frozen": True}

    cpu: float = Field(ge=MIN_RESOURCE_DEMAND, description="CPU cores")
    mem_gb: float = Field(ge=MIN_RESOURCE_DEMAND, description="Memory, GB")
    disk_gb: float = Field(ge=MIN_RESOURCE_DEMAND, description="Disk, GB")
    net_mbps: float = Field(ge=MIN_RESOURCE_DEMAND, description="Network bandwidth, Mbps")

    def __add__(self, other: ResourceDemand) -> ResourceDemand:
        return ResourceDemand(
            cpu=self.cpu + other.cpu,
            mem_gb=self.mem_gb + other.mem_gb,
            disk_gb=self.disk_gb + other.disk_gb,
            net_mbps=self.net_mbps + other.net_mbps,
        )


class Task(BaseModel):
    """A single schedulable unit within a job's DAG.

    `task_name` is tenant-authored free text (blueprint §6, attack surface).
    Everything else here is system-measured or system-assigned.
    """

    model_config = {"frozen": True}

    task_id: UUID = Field(default_factory=uuid4)
    task_name: str = Field(min_length=1, max_length=512)
    demand: ResourceDemand
    est_duration_s: int = Field(ge=MIN_DURATION_S)


class TaskEdge(BaseModel):
    """A directed data-dependency edge between two tasks in the same job's DAG."""

    model_config = {"frozen": True}

    parent_task_id: UUID
    child_task_id: UUID
    data_transfer_gb: float = Field(ge=MIN_RESOURCE_DEMAND)

    @model_validator(mode="after")
    def _no_self_loop(self) -> TaskEdge:
        if self.parent_task_id == self.child_task_id:
            raise ValueError("a task cannot depend on itself")
        return self


class Job(BaseModel):
    """A tenant's job submission: a DAG of tasks plus scheduling metadata.

    `description` is the primary attack surface field (blueprint §5). It is
    kept as a plain string here — the trust-aware encoder, not this model,
    is responsible for separating it from system-authored context before
    anything reaches the LLM.
    """

    model_config = {"frozen": True}

    job_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    priority: int = Field(ge=0, le=100, default=0)
    deadline_s: int | None = Field(default=None, ge=1)
    weight: float = Field(gt=0.0, default=1.0)
    description: str = Field(default="", max_length=4096)
    tasks: tuple[Task, ...] = Field(min_length=1)
    edges: tuple[TaskEdge, ...] = Field(default_factory=tuple)

    # Ground-truth attack labels. Never read outside eval/metrics/.
    is_synthetic_attack: bool = False
    attack_payload_type: AttackFamily | None = None

    @model_validator(mode="after")
    def _edges_reference_known_tasks_and_form_a_dag(self) -> Job:
        task_ids = {task.task_id for task in self.tasks}
        for edge in self.edges:
            if edge.parent_task_id not in task_ids or edge.child_task_id not in task_ids:
                raise ValueError(
                    f"edge {edge.parent_task_id}->{edge.child_task_id} references a task_id "
                    "not present in this job's tasks"
                )
        if not nx.is_directed_acyclic_graph(_edges_to_digraph(task_ids, self.edges)):
            raise ValueError("job's task_edges contain a cycle — must be a DAG")
        return self

    @model_validator(mode="after")
    def _attack_label_consistency(self) -> Job:
        if self.attack_payload_type is not None and not self.is_synthetic_attack:
            raise ValueError("attack_payload_type set but is_synthetic_attack is False")
        return self

    def total_demand(self) -> ResourceDemand:
        """Sum of every task's resource demand — the numerator DRF needs."""
        total = ResourceDemand(cpu=0.0, mem_gb=0.0, disk_gb=0.0, net_mbps=0.0)
        for task in self.tasks:
            total = total + task.demand
        return total

    def to_networkx(self) -> nx.DiGraph:
        """Build the task DAG as a `networkx.DiGraph`, keyed by `task_id`."""
        task_ids = {task.task_id for task in self.tasks}
        return _edges_to_digraph(task_ids, self.edges)


def _edges_to_digraph(task_ids: set[UUID], edges: tuple[TaskEdge, ...]) -> nx.DiGraph:
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(task_ids)
    graph.add_edges_from((edge.parent_task_id, edge.child_task_id) for edge in edges)
    return graph


class NodeCapacity(BaseModel):
    """A cluster node's resource capacity (blueprint §9 `nodes` table)."""

    model_config = {"frozen": True}

    node_id: UUID = Field(default_factory=uuid4)
    zone: str = Field(min_length=1, max_length=64)
    capacity: ResourceDemand
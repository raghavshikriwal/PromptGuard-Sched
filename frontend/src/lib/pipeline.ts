export type DefenseConfigId = "none" | "guard_only" | "trust_only" | "ilp_anomaly_only" | "full";

export type TrustZone = "tenant" | "mixed" | "trusted";

export interface DefenseConfig {
  readonly id: DefenseConfigId;
  readonly code: string;
  readonly label: string;
}

export interface PipelineStage {
  readonly id: string;
  readonly name: string;
  readonly zone: TrustZone;
  readonly summary: string;
  readonly input: string;
  readonly output: string;
  readonly codePath: string | null;
  readonly activeIn: "always" | readonly DefenseConfigId[];
}

export const DEFENSE_CONFIGS: readonly DefenseConfig[] = [
  { id: "none", code: "C0", label: "None" },
  { id: "guard_only", code: "C1", label: "Guard only" },
  { id: "trust_only", code: "C2", label: "Trust boundary only" },
  { id: "ilp_anomaly_only", code: "C3", label: "ILP + anomaly cap" },
  { id: "full", code: "C4", label: "Full" },
];

export const ZONE_LABEL: Record<TrustZone, string> = {
  tenant: "Tenant-controlled",
  mixed: "Touches tenant text",
  trusted: "Trusted scheduler code",
};

export const DEFAULT_CONFIG_ID: DefenseConfigId = "full";
export const DEFAULT_STAGE_ID = "guard";

export const PIPELINE_STAGES: readonly PipelineStage[] = [
  {
    id: "submission",
    name: "Tenant job submission",
    zone: "tenant",
    summary:
      "A tenant submits a valid job. Free-text fields such as the description and task names are the attacker-controlled input.",
    input: "Job record with description and task names",
    output: "Validated job",
    codePath: null,
    activeIn: "always",
  },
  {
    id: "guard",
    name: "Input guard",
    zone: "mixed",
    summary:
      "Rule-based check of tenant text for instruction-like patterns. It is heuristic, so it can miss paraphrases and obfuscated text.",
    input: "Tenant-authored text",
    output: "Guard score and flag",
    codePath: "src/guard/classifier.py",
    activeIn: ["guard_only", "full"],
  },
  {
    id: "encoder",
    name: "Trust-boundary encoding",
    zone: "mixed",
    summary:
      "Separates trusted scheduler context from tenant text and marks the boundary. When off, tenant text goes into the prompt without a marked boundary.",
    input: "Job, cluster state, guard result",
    output: "Structured model context",
    codePath: "src/encoder/state_encoder.py",
    activeIn: ["trust_only", "full"],
  },
  {
    id: "llm",
    name: "LLM candidate generation",
    zone: "mixed",
    summary: "The model proposes resource shares. It has no authority to execute an assignment.",
    input: "Structured model context",
    output: "Candidate allocation",
    codePath: "src/llm/client.py",
    activeIn: "always",
  },
  {
    id: "parse",
    name: "Parsing and validation",
    zone: "trusted",
    summary:
      "Structured output is parsed with bounded retries and checked against the schema and share limits.",
    input: "Raw model text",
    output: "Validated candidate",
    codePath: "src/llm/schema.py",
    activeIn: "always",
  },
  {
    id: "anomaly",
    name: "Anomaly cap",
    zone: "trusted",
    summary:
      "Caps a proposal that exceeds the job's DRF entitlement by more than the configured threshold. It judges numbers, not intent.",
    input: "Candidate and DRF entitlement",
    output: "Capped candidate",
    codePath: "src/anomaly/check.py",
    activeIn: ["ilp_anomaly_only", "full"],
  },
  {
    id: "ilp",
    name: "ILP refinement",
    zone: "trusted",
    summary:
      "Finds the allocation closest to the proposal under the modelled constraints, using CBC with a short time limit.",
    input: "Candidate allocation",
    output: "Refined allocation",
    codePath: "src/ilp/refine.py",
    activeIn: "always",
  },
  {
    id: "capacity",
    name: "Capacity check",
    zone: "trusted",
    summary: "Validates the final allocation against modelled cluster capacity in the ledger.",
    input: "Refined allocation",
    output: "Accepted allocation",
    codePath: "src/scheduler/capacity.py",
    activeIn: "always",
  },
  {
    id: "persist",
    name: "Persistence",
    zone: "trusted",
    summary: "Stores the decision, defense flags and per-stage latency for metrics and statistics.",
    input: "Final decision and telemetry",
    output: "Database rows",
    codePath: "src/scheduler/persistence.py",
    activeIn: "always",
  },
];

export function getConfig(id: DefenseConfigId): DefenseConfig {
  const found = DEFENSE_CONFIGS.find((config) => config.id === id);
  if (!found) {
    throw new Error(`Unknown defense config: ${id}`);
  }
  return found;
}

export function isStageActive(stage: PipelineStage, configId: DefenseConfigId): boolean {
  return stage.activeIn === "always" || stage.activeIn.includes(configId);
}

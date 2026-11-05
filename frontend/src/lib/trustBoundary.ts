import { PIPELINE_STAGES, getConfig, type PipelineStage, type TrustZone } from "./pipeline";

export const ZONE_ORDER: readonly TrustZone[] = ["tenant", "mixed", "trusted"];

export interface PromptInputGroup {
  readonly zone: "tenant" | "trusted";
  readonly title: string;
  readonly items: readonly string[];
}

export const PROMPT_INPUT_GROUPS: readonly PromptInputGroup[] = [
  {
    zone: "tenant",
    title: "From the tenant (untrusted)",
    items: ["Job description", "Task names"],
  },
  {
    zone: "trusted",
    title: "From the scheduler (trusted)",
    items: ["System-authored instructions", "Cluster capacities and telemetry"],
  },
];

const BOUNDARY_STAGE_ID = "encoder";

export function stagesByZone(zone: TrustZone): PipelineStage[] {
  return PIPELINE_STAGES.filter((stage) => stage.zone === zone);
}

export function boundaryConfigCodes(): string[] {
  const stage = PIPELINE_STAGES.find((item) => item.id === BOUNDARY_STAGE_ID);
  if (!stage || stage.activeIn === "always") {
    throw new Error(`Stage "${BOUNDARY_STAGE_ID}" must list the configurations that enable it`);
  }
  return stage.activeIn.map((id) => getConfig(id).code);
}

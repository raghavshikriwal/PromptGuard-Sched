import type { Campaign, Decision, Experiment } from "./dataset";

export interface StripPoint {
  readonly jobId: string;
  readonly delta: number;
  readonly family: string | null;
}

/**
 * Allocation deviation (Δ) of every injected job, grouped by defense config, for one campaign.
 * Smoke tests are left out, exactly as in the aggregates, so the dots match the chart above.
 */
export function injectedDeltasByConfig(
  campaign: Campaign,
  experiments: readonly Experiment[],
  decisions: readonly Decision[],
): Map<string, StripPoint[]> {
  const configByExperiment = new Map(
    experiments
      .filter((item) => item.group_id === campaign.groupId && !item.smoke_test)
      .map((item) => [item.experiment_id, item.config_code]),
  );
  const byConfig = new Map<string, StripPoint[]>();
  for (const decision of decisions) {
    const code = configByExperiment.get(decision.experiment_id);
    if (code === undefined || !decision.is_attack) continue;
    byConfig.set(code, [
      ...(byConfig.get(code) ?? []),
      { jobId: decision.job_id, delta: decision.delta_j, family: decision.family },
    ]);
  }
  return byConfig;
}

/** Stable value in [-0.5, 0.5) from a job id, so the vertical jitter never changes between renders. */
export function jitter(jobId: string): number {
  let hash = 0;
  for (const char of jobId) hash = (hash * 31 + char.charCodeAt(0)) % 1000;
  return hash / 1000 - 0.5;
}

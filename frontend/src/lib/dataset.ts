import { z } from "zod";

/**
 * Schemas for the files written by `python -m eval.export.canonical_dataset`.
 * Parsing is strict on the fields the site reads: if the exporter's schema drifts,
 * the Results page shows an error instead of drawing wrong numbers.
 */

export const SUPPORTED_SCHEMA_VERSION = 1;

const rate = z.object({
  successes: z.number(),
  n: z.number(),
  value: z.number().nullable(),
});

export const manifestSchema = z.object({
  schema_version: z.literal(SUPPORTED_SCHEMA_VERSION),
  generated_at: z.string(),
  git_commit: z.string().nullable(),
  dataset_sha256: z.string(),
  thresholds: z.array(z.number()),
  tau_default: z.number(),
  evidence_rule: z.string(),
  sources: z.array(
    z.object({
      database: z.string(),
      bytes: z.number(),
      sha256: z.string(),
      experiments: z.number(),
    }),
  ),
  counts: z.object({
    databases: z.number(),
    experiments_found: z.number(),
    experiments_canonical: z.number(),
    attack_experiments: z.number(),
    baseline_experiments: z.number(),
    decisions: z.number(),
    aggregate_rows: z.number(),
  }),
});

export const seedPointSchema = z.object({
  seed: z.number(),
  experiment_id: z.string(),
  value: z.number().nullable(),
  n: z.number(),
});

export const metricAggregateSchema = z.object({
  mean: z.number().nullable(),
  half_width: z.number().nullable(),
  n_seeds: z.number(),
  points: z.array(seedPointSchema),
});

export const aggregateRowSchema = z.object({
  group_id: z.string(),
  source_database: z.string(),
  model_id: z.string(),
  injection_ratio: z.number(),
  config: z.string(),
  config_code: z.string(),
  seeds: z.array(z.number()),
  evidence: z.enum(["pilot", "exploratory", "confirmatory"]),
  injected_per_run: z.array(z.number()),
  metrics: z.record(z.string(), metricAggregateSchema),
  paired_asr_vs_c0: z
    .object({
      mean_reduction: z.number().nullable(),
      half_width: z.number().nullable(),
      n_pairs: z.number(),
    })
    .nullable(),
  caveats: z.array(z.string()),
});

export const experimentSchema = z.object({
  experiment_id: z.string(),
  kind: z.enum(["attack", "baseline"]),
  smoke_test: z.boolean(),
  group_id: z.string(),
  config_code: z.string(),
  model_id: z.string(),
  seed: z.number(),
  injection_ratio: z.number(),
  primary_source: z.string(),
  decisions: z.number(),
  injected: z.number(),
  benign: z.number(),
  missing_decisions: z.number().nullable(),
  asr: z.record(z.string(), rate),
});

export const integritySchema = z.object({
  skipped_databases: z.array(z.object({ database: z.string(), reason: z.string() })),
  databases_without_experiments: z.array(z.string()),
  duplicate_experiments: z.array(z.unknown()),
  conflicting_experiments: z.array(z.unknown()),
  repeat_runs_not_deduplicated: z.array(z.unknown()),
  smoke_test_experiments_excluded_from_aggregates: z.array(z.string()),
  unfinished_experiments: z.array(z.string()),
  missing_decisions: z.array(
    z.object({
      experiment_id: z.string(),
      database: z.string(),
      config: z.string(),
      seed: z.number(),
      expected: z.number().nullable(),
      present: z.number(),
      missing: z.number(),
    }),
  ),
  not_recorded_in_databases: z.array(z.string()),
});

export type Manifest = z.infer<typeof manifestSchema>;
export type AggregateRow = z.infer<typeof aggregateRowSchema>;
export type MetricAggregate = z.infer<typeof metricAggregateSchema>;
export type Experiment = z.infer<typeof experimentSchema>;
export type Integrity = z.infer<typeof integritySchema>;

export interface Dataset {
  readonly manifest: Manifest;
  readonly aggregates: readonly AggregateRow[];
  readonly experiments: readonly Experiment[];
  readonly integrity: Integrity;
}

export interface Campaign {
  readonly groupId: string;
  readonly label: string;
  readonly rows: readonly AggregateRow[];
}

const CONFIG_ORDER = ["C0", "C1", "C2", "C3", "C4"];

export function configRank(code: string): number {
  const rank = CONFIG_ORDER.indexOf(code);
  return rank === -1 ? CONFIG_ORDER.length : rank;
}

/** One campaign = one source database at one injection ratio (seeds are never pooled across them). */
export function groupCampaigns(aggregates: readonly AggregateRow[]): Campaign[] {
  const byGroup = new Map<string, AggregateRow[]>();
  for (const row of aggregates) {
    byGroup.set(row.group_id, [...(byGroup.get(row.group_id) ?? []), row]);
  }
  return [...byGroup.entries()]
    .map(([groupId, rows]) => {
      const sorted = [...rows].sort(
        (a, b) => configRank(a.config_code) - configRank(b.config_code),
      );
      const first = sorted[0];
      if (!first) throw new Error(`Campaign ${groupId} has no rows`);
      return {
        groupId,
        label: `${first.source_database} · ${Math.round(first.injection_ratio * 100)}% injected`,
        rows: sorted,
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function metricKey(tau: number): string {
  return `asr@${tau.toFixed(2)}`;
}

export function formatPercent(value: number | null): string {
  return value === null ? "n/a" : `${(value * 100).toFixed(1)}%`;
}

/** "50.0% ± 12.3" or "50.0% (no CI: 1 seed)". Never prints ±0 for a missing interval. */
export function formatMeanCi(metric: MetricAggregate | undefined): string {
  if (!metric || metric.mean === null) return "n/a";
  if (metric.half_width === null) return `${formatPercent(metric.mean)} (no CI: 1 seed)`;
  return `${formatPercent(metric.mean)} ± ${(metric.half_width * 100).toFixed(1)}`;
}

export type PairedReduction = NonNullable<AggregateRow["paired_asr_vs_c0"]>;

/** "25.6% ± 41.4 (3 pairs)": the interval is always shown, so a CI that crosses zero is visible. */
export function formatPaired(paired: PairedReduction | null): string {
  if (!paired || paired.mean_reduction === null) return "–";
  const pairs = `${paired.n_pairs} ${paired.n_pairs === 1 ? "pair" : "pairs"}`;
  if (paired.half_width === null)
    return `${formatPercent(paired.mean_reduction)} (${pairs}, no CI)`;
  return `${formatPercent(paired.mean_reduction)} ± ${(paired.half_width * 100).toFixed(1)} (${pairs})`;
}

export function parseJson<T>(schema: z.ZodType<T>, name: string, raw: unknown): T {
  const result = schema.safeParse(raw);
  if (!result.success) {
    throw new Error(`${name} does not match the expected schema: ${result.error.message}`);
  }
  return result.data;
}

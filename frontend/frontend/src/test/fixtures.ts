import type { AggregateRow, Integrity, Manifest } from "../lib/dataset";

export const MANIFEST: Manifest = {
  schema_version: 1,
  generated_at: "2026-11-05T04:00:00+00:00",
  git_commit: null,
  dataset_sha256: "abcdef0123456789abcdef",
  thresholds: [0.1, 0.25, 0.5],
  tau_default: 0.25,
  evidence_rule: "test",
  sources: [{ database: "abl.db", bytes: 1, sha256: "x", experiments: 4 }],
  counts: {
    databases: 1,
    experiments_found: 4,
    experiments_canonical: 4,
    attack_experiments: 4,
    baseline_experiments: 0,
    decisions: 40,
    aggregate_rows: 2,
  },
};

function row(code: string, config: string, values: [number, number], reduction: number | null) {
  const mean = (values[0] + values[1]) / 2;
  const metric = {
    mean,
    half_width: 0.2,
    n_seeds: 2,
    points: [
      { seed: 0, experiment_id: `${code}-0`, value: values[0], n: 6 },
      { seed: 1, experiment_id: `${code}-1`, value: values[1], n: 6 },
    ],
  };
  const aggregate: AggregateRow = {
    group_id: "abl.db|Qwen/Qwen2.5-3B-Instruct|0.6",
    source_database: "abl.db",
    model_id: "Qwen/Qwen2.5-3B-Instruct",
    injection_ratio: 0.6,
    config,
    config_code: code,
    seeds: [0, 1],
    evidence: "exploratory",
    injected_per_run: [6, 6],
    metrics: { "asr@0.10": metric, "asr@0.25": metric, "asr@0.50": { ...metric, mean: 0.1 } },
    paired_asr_vs_c0:
      reduction === null ? null : { mean_reduction: reduction, half_width: 0.1, n_pairs: 2 },
    caveats: ["2 seed(s); at least 3 recommended"],
  };
  return aggregate;
}

export const AGGREGATES: AggregateRow[] = [
  row("C4", "full", [0.1, 0.2], 0.5),
  row("C0", "none", [0.6, 0.7], null),
];

export const INTEGRITY: Integrity = {
  skipped_databases: [{ database: "gate_hf3.db", reason: "missing tables: experiments" }],
  databases_without_experiments: ["injection_5pct_qwen_seed0.db"],
  duplicate_experiments: [],
  conflicting_experiments: [],
  repeat_runs_not_deduplicated: [],
  smoke_test_experiments_excluded_from_aggregates: ["s1"],
  unfinished_experiments: [],
  missing_decisions: [
    {
      experiment_id: "m1",
      database: "abl.db",
      config: "C0",
      seed: 2,
      expected: 10,
      present: 9,
      missing: 1,
    },
  ],
  not_recorded_in_databases: ["model revision"],
};

export function fetchStub(overrides: Record<string, unknown> = {}): typeof fetch {
  const files: Record<string, unknown> = {
    "manifest.json": MANIFEST,
    "aggregates.json": AGGREGATES,
    "experiments.json": [],
    "integrity.json": INTEGRITY,
    "decisions.json": {
      columns: ["experiment_id", "job_id", "is_attack", "family", "delta_j"],
      rows: [],
    },
    ...overrides,
  };
  return (async (input: RequestInfo | URL) => {
    const name = String(input).split("/").pop() ?? "";
    if (!(name in files)) return new Response("missing", { status: 404 });
    return new Response(JSON.stringify(files[name]), { status: 200 });
  }) as typeof fetch;
}

import { describe, expect, it } from "vitest";
import { AGGREGATES, MANIFEST } from "../test/fixtures";
import {
  aggregateRowSchema,
  formatMeanCi,
  formatPaired,
  formatPercent,
  groupCampaigns,
  manifestSchema,
  metricKey,
  parseJson,
} from "./dataset";

describe("dataset helpers", () => {
  it("formats thresholds the way the exporter keys them", () => {
    expect(metricKey(0.1)).toBe("asr@0.10");
    expect(metricKey(0.25)).toBe("asr@0.25");
  });

  it("formats percentages and missing values", () => {
    expect(formatPercent(0.5)).toBe("50.0%");
    expect(formatPercent(null)).toBe("n/a");
  });

  it("never prints a zero-width interval for a single seed", () => {
    const one = { mean: 0.5, half_width: null, n_seeds: 1, points: [] };
    expect(formatMeanCi(one)).toBe("50.0% (no CI: 1 seed)");
    expect(formatMeanCi({ ...one, half_width: 0.123 })).toBe("50.0% ± 12.3");
    expect(formatMeanCi(undefined)).toBe("n/a");
  });

  it("orders configurations C0 to C4 inside one campaign", () => {
    const [campaign] = groupCampaigns(AGGREGATES);
    expect(campaign?.rows.map((r) => r.config_code)).toEqual(["C0", "C4"]);
    expect(campaign?.label).toBe("abl.db · 60% injected");
  });

  it("does not merge different databases into one campaign", () => {
    const other = { ...AGGREGATES[0]!, group_id: "other.db|m|0.6", source_database: "other.db" };
    expect(groupCampaigns([...AGGREGATES, other])).toHaveLength(2);
  });
});

describe("paired reduction", () => {
  it("always shows the interval and handles missing pieces", () => {
    expect(formatPaired({ mean_reduction: 0.256, half_width: 0.414, n_pairs: 3 })).toBe(
      "25.6% ± 41.4 (3 pairs)",
    );
    expect(formatPaired({ mean_reduction: 0.5, half_width: null, n_pairs: 1 })).toBe(
      "50.0% (1 pair, no CI)",
    );
    expect(formatPaired(null)).toBe("–");
  });
});

describe("schema validation", () => {
  it("accepts a valid manifest and rejects a different schema version", () => {
    expect(parseJson(manifestSchema, "manifest.json", MANIFEST).counts.decisions).toBe(40);
    expect(() =>
      parseJson(manifestSchema, "manifest.json", { ...MANIFEST, schema_version: 2 }),
    ).toThrow(/manifest.json does not match/);
  });

  it("fails loudly when a field the site needs is missing", () => {
    const { metrics: _metrics, ...broken } = AGGREGATES[0]!;
    expect(() => parseJson(aggregateRowSchema, "aggregates.json", broken)).toThrow(
      /aggregates.json/,
    );
  });
});

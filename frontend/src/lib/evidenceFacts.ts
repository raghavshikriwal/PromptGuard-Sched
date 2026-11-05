import { groupCampaigns, type AggregateRow, type Dataset } from "./dataset";
import type { EvidenceLevel } from "./evidence";

const LEVEL_ORDER: readonly EvidenceLevel[] = ["pilot", "exploratory", "confirmatory"];
const PERCENT = 100;

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** The strongest evidence level any aggregate row has reached, or null when there are no rows. */
export function deriveEvidenceLevel(rows: readonly AggregateRow[]): EvidenceLevel | null {
  const ranks = rows.map((row) => LEVEL_ORDER.indexOf(row.evidence));
  return ranks.length === 0 ? null : (LEVEL_ORDER[Math.max(...ranks)] ?? null);
}

/** Plain-language facts about the data behind the site, computed from the exported dataset. */
export function deriveEvidenceFacts(dataset: Dataset): string[] {
  const { manifest, integrity, aggregates } = dataset;
  const facts: string[] = [];

  const withExperiments = manifest.sources.filter((source) => source.experiments > 0).length;
  facts.push(
    `${plural(manifest.counts.experiments_canonical, "experiment")} and ` +
      `${plural(manifest.counts.decisions, "scheduling decision")} from ` +
      `${withExperiments} of ${plural(manifest.counts.databases, "database")}.`,
  );

  const empty = manifest.counts.databases - withExperiments;
  if (empty > 0) {
    facts.push(`${plural(empty, "database")} held no usable experiments and add nothing here.`);
  }

  const models = [...new Set(aggregates.map((row) => row.model_id))];
  if (models.length > 0) facts.push(`Model: ${models.join(", ")}.`);

  for (const campaign of groupCampaigns(aggregates)) {
    const rows = campaign.rows;
    const first = rows[0];
    if (!first) continue;
    const injected = rows.flatMap((row) => row.injected_per_run);
    const smallest = Math.min(...injected);
    const largest = Math.max(...injected);
    const seeds = Math.max(...rows.map((row) => row.seeds.length));
    const ratio = `${Math.round(first.injection_ratio * PERCENT)}%`;
    const steps =
      smallest === largest
        ? `each run has ${plural(smallest, "injected job")}, so rates move in steps of 1/${smallest}`
        : `runs have ${smallest} to ${largest} injected jobs, so rates move in coarse steps`;
    facts.push(`At ${ratio} injection (${plural(seeds, "seed")}), ${steps}.`);
  }

  const missing = integrity.missing_decisions.reduce((sum, item) => sum + item.missing, 0);
  if (missing > 0) {
    facts.push(
      `${plural(missing, "decision")} missing across ` +
        `${plural(integrity.missing_decisions.length, "run")}. Missing decisions are reported, not hidden.`,
    );
  }

  const smoke = integrity.smoke_test_experiments_excluded_from_aggregates.length;
  if (smoke > 0) {
    facts.push(`${plural(smoke, "smoke-test run")} kept out of every aggregate.`);
  }
  return facts;
}

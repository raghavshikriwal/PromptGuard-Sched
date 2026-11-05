import { describe, expect, it } from "vitest";
import type { Dataset } from "./dataset";
import { deriveEvidenceFacts, deriveEvidenceLevel } from "./evidenceFacts";
import { AGGREGATES, INTEGRITY, MANIFEST } from "../test/fixtures";

const DATASET: Dataset = {
  manifest: MANIFEST,
  aggregates: AGGREGATES,
  experiments: [],
  integrity: INTEGRITY,
};

describe("deriveEvidenceFacts", () => {
  const facts = deriveEvidenceFacts(DATASET);

  it("takes counts from the manifest, not from constants", () => {
    expect(facts[0]).toBe("4 experiments and 40 scheduling decisions from 1 of 1 database.");
  });

  it("explains the step size of rates from injected jobs per run", () => {
    expect(facts).toContain(
      "At 60% injection (2 seeds), each run has 6 injected jobs, so rates move in steps of 1/6.",
    );
  });

  it("reports missing decisions and smoke tests", () => {
    expect(facts.some((fact) => fact.startsWith("1 decision missing across 1 run"))).toBe(true);
    expect(facts).toContain("1 smoke-test run kept out of every aggregate.");
  });

  it("says nothing about empty databases when there are none", () => {
    expect(facts.some((fact) => fact.includes("no usable experiments"))).toBe(false);
  });

  it("notes databases that held no experiments", () => {
    const manifest = { ...MANIFEST, counts: { ...MANIFEST.counts, databases: 3 } };
    expect(deriveEvidenceFacts({ ...DATASET, manifest })).toContain(
      "2 databases held no usable experiments and add nothing here.",
    );
  });
});

describe("deriveEvidenceLevel", () => {
  it("is null without rows", () => {
    expect(deriveEvidenceLevel([])).toBeNull();
  });

  it("uses the strongest level in the data", () => {
    const [first] = AGGREGATES;
    if (!first) throw new Error("fixture is empty");
    const pilot = { ...first, evidence: "pilot" as const };
    expect(deriveEvidenceLevel([pilot])).toBe("pilot");
    expect(deriveEvidenceLevel([pilot, first])).toBe("exploratory");
  });
});

import { describe, expect, it } from "vitest";
import {
  CURRENT_EVIDENCE_LEVEL,
  EVIDENCE_FACTS,
  EVIDENCE_LEVEL_LABEL,
  RECORDED_EXAMPLE,
} from "./evidence";

describe("evidence data", () => {
  it("labels the current evidence as exploratory", () => {
    expect(EVIDENCE_LEVEL_LABEL[CURRENT_EVIDENCE_LEVEL]).toBe("Exploratory evidence");
  });

  it("lists non-empty evidence facts", () => {
    expect(EVIDENCE_FACTS.length).toBeGreaterThan(0);
    expect(EVIDENCE_FACTS.every((fact) => fact.trim().length > 0)).toBe(true);
  });

  it("records final shares below the proposed share for every resource", () => {
    for (const item of RECORDED_EXAMPLE.finalShares) {
      expect(item.share).toBeLessThan(RECORDED_EXAMPLE.proposedShare);
    }
  });

  it("keeps the guard score within the zero-to-one range", () => {
    expect(RECORDED_EXAMPLE.guardScore).toBeGreaterThan(0);
    expect(RECORDED_EXAMPLE.guardScore).toBeLessThanOrEqual(1);
  });
});

import { describe, expect, it } from "vitest";
import { EVIDENCE_LEVEL_LABEL, RECORDED_EXAMPLE } from "./evidence";

describe("evidence data", () => {
  it("has a label for every evidence level", () => {
    expect(EVIDENCE_LEVEL_LABEL.exploratory).toBe("Exploratory evidence");
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

import { describe, expect, it } from "vitest";
import { PIPELINE_STAGES } from "./pipeline";
import { ZONE_ORDER, boundaryConfigCodes, stagesByZone } from "./trustBoundary";

describe("trust boundary data", () => {
  it("places every stage in exactly one zone", () => {
    const total = ZONE_ORDER.reduce((sum, zone) => sum + stagesByZone(zone).length, 0);
    expect(total).toBe(PIPELINE_STAGES.length);
  });

  it("keeps tenant submission in the tenant zone", () => {
    expect(stagesByZone("tenant").map((stage) => stage.id)).toEqual(["submission"]);
  });

  it("keeps the anomaly cap in the trusted zone", () => {
    expect(stagesByZone("trusted").map((stage) => stage.id)).toContain("anomaly");
  });

  it("reports C2 and C4 as the configurations with a trust boundary", () => {
    expect(boundaryConfigCodes()).toEqual(["C2", "C4"]);
  });
});

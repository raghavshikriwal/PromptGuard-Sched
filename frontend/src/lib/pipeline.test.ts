import { describe, expect, it } from "vitest";
import {
  DEFENSE_CONFIGS,
  PIPELINE_STAGES,
  getConfig,
  isStageActive,
  type DefenseConfigId,
} from "./pipeline";

function activeIds(configId: DefenseConfigId): string[] {
  return PIPELINE_STAGES.filter((stage) => isStageActive(stage, configId)).map((s) => s.id);
}

describe("pipeline stages", () => {
  it("has unique stage ids", () => {
    const ids = PIPELINE_STAGES.map((stage) => stage.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("runs only the always-on stages in C0", () => {
    expect(activeIds("none")).toEqual(["submission", "llm", "parse", "ilp", "capacity", "persist"]);
  });

  it("enables each defense layer in its own configuration", () => {
    expect(activeIds("guard_only")).toContain("guard");
    expect(activeIds("trust_only")).toContain("encoder");
    expect(activeIds("ilp_anomaly_only")).toContain("anomaly");
  });

  it("enables every stage in C4", () => {
    expect(activeIds("full")).toHaveLength(PIPELINE_STAGES.length);
  });

  it("looks up configs and rejects unknown ids", () => {
    expect(getConfig("none").code).toBe("C0");
    expect(DEFENSE_CONFIGS).toHaveLength(5);
    expect(() => getConfig("bogus" as DefenseConfigId)).toThrow("Unknown defense config");
  });
});

import { describe, expect, it } from "vitest";
import { groupCampaigns, parseDecisions, type Experiment } from "./dataset";
import { injectedDeltasByConfig, jitter } from "./strip";
import { AGGREGATES } from "../test/fixtures";

const campaign = groupCampaigns(AGGREGATES)[0];
if (!campaign) throw new Error("fixture is empty");
const GROUP_ID = campaign.groupId;

function experiment(id: string, code: string, smoke = false): Experiment {
  return {
    experiment_id: id,
    kind: "attack",
    smoke_test: smoke,
    group_id: GROUP_ID,
    config_code: code,
    model_id: "m",
    seed: 0,
    injection_ratio: 0.6,
    primary_source: "abl.db",
    decisions: 2,
    injected: 1,
    benign: 1,
    missing_decisions: 0,
    asr: {},
  };
}

const DECISIONS = parseDecisions({
  columns: ["experiment_id", "job_id", "is_attack", "family", "delta_j", "extra"],
  rows: [
    ["a", "j1", true, "role_confusion", 0.4, 1],
    ["a", "j2", false, null, 0.1, 1],
    ["b", "j3", true, "direct_override", -0.2, 1],
    ["smoke", "j4", true, "direct_override", 0.9, 1],
  ],
});

describe("parseDecisions", () => {
  it("maps columns to records and ignores unknown columns", () => {
    expect(DECISIONS[0]).toEqual({
      experiment_id: "a",
      job_id: "j1",
      is_attack: true,
      family: "role_confusion",
      delta_j: 0.4,
    });
  });

  it("fails loudly when a column has the wrong type", () => {
    expect(() =>
      parseDecisions({
        columns: ["experiment_id", "job_id", "is_attack", "family", "delta_j"],
        rows: [["a", "j", "yes", null, 0.1]],
      }),
    ).toThrow(/decisions.json/);
  });
});

describe("injectedDeltasByConfig", () => {
  const experiments = [
    experiment("a", "C0"),
    experiment("b", "C4"),
    experiment("smoke", "C0", true),
  ];
  const result = injectedDeltasByConfig(campaign, experiments, DECISIONS);

  it("keeps only injected jobs of this campaign's non-smoke experiments", () => {
    expect(result.get("C0")?.map((point) => point.jobId)).toEqual(["j1"]);
    expect(result.get("C4")?.map((point) => point.delta)).toEqual([-0.2]);
  });
});

describe("jitter", () => {
  it("is deterministic and bounded", () => {
    expect(jitter("abc")).toBe(jitter("abc"));
    for (const id of ["a", "job-1", "f3a9"]) {
      expect(Math.abs(jitter(id))).toBeLessThanOrEqual(0.5);
    }
  });
});

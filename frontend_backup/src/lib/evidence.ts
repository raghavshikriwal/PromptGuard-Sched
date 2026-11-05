export type EvidenceLevel = "pilot" | "exploratory" | "confirmatory";

export const EVIDENCE_LEVEL_LABEL: Record<EvidenceLevel, string> = {
  pilot: "Pilot evidence",
  exploratory: "Exploratory evidence",
  confirmatory: "Confirmatory evidence",
};

export const CURRENT_EVIDENCE_LEVEL: EvidenceLevel = "exploratory";

export const EVIDENCE_FACTS: readonly string[] = [
  "42 real Qwen2.5-3B-Instruct run records across 14 databases.",
  "In the 10% injection pilot each run has only 3 injected jobs, so rates move in steps of one third.",
  "The 60% stress test uses 3 seeds, so confidence intervals are wide.",
  "One 10% run persisted 29 of 30 decisions. Missing decisions are reported, not hidden.",
];

export interface ResourceShare {
  readonly resource: string;
  readonly share: number;
  readonly display: string;
}

export interface RecordedExample {
  readonly sourceNote: string;
  readonly configCode: string;
  readonly guardScore: number;
  readonly proposedShare: number;
  readonly cappedMaxDeviation: number;
  readonly solverStatus: string;
  readonly finalShares: readonly ResourceShare[];
}

export const RECORDED_EXAMPLE: RecordedExample = {
  sourceNote:
    "One C4 job from an earlier database audit (README section 8.4). Not an aggregate result.",
  configCode: "C4",
  guardScore: 0.88,
  proposedShare: 0.9,
  cappedMaxDeviation: 0.2832,
  solverStatus: "Optimal",
  finalShares: [
    { resource: "CPU", share: 0.05997, display: "0.05997" },
    { resource: "Memory", share: 0.02005, display: "0.02005" },
    { resource: "Disk", share: 0, display: "near zero" },
    { resource: "Network", share: 0.2832, display: "0.2832" },
  ],
};

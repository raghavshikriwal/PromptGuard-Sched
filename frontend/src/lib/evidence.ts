export type EvidenceLevel = "pilot" | "exploratory" | "confirmatory";

export const EVIDENCE_LEVEL_LABEL: Record<EvidenceLevel, string> = {
  pilot: "Pilot evidence",
  exploratory: "Exploratory evidence",
  confirmatory: "Confirmatory evidence",
};

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

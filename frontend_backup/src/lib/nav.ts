export interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly summary: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { path: "/", label: "Home", summary: "The research question and current evidence status." },
  {
    path: "/pipeline",
    label: "Pipeline",
    summary: "Interactive view of encoder, guard, LLM, anomaly cap and ILP stages.",
  },
  {
    path: "/results",
    label: "Results",
    summary: "Attack success and fairness results with provenance and missing-data disclosure.",
  },
  { path: "/docs", label: "Docs", summary: "Setup, run commands and reproducibility steps." },
  {
    path: "/research",
    label: "Research",
    summary: "Threat model, metric definitions, method and limitations.",
  },
];

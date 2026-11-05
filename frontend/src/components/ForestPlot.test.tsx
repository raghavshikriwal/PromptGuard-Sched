import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AGGREGATES } from "../test/fixtures";
import ForestPlot, { pairedRows } from "./ForestPlot";

describe("ForestPlot", () => {
  it("keeps only configs that have a paired reduction", () => {
    expect(pairedRows(AGGREGATES).map((row) => row.config_code)).toEqual(["C4"]);
  });

  it("describes each interval in its accessible label", () => {
    render(<ForestPlot rows={AGGREGATES} tau={0.25} />);
    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).toContain("threshold 0.25");
    expect(label).toContain("C4 50.0% ± 10.0 (2 pairs)");
  });

  it("draws nothing when no config has a paired reduction", () => {
    const unpaired = AGGREGATES.map((row) => ({ ...row, paired_asr_vs_c0: null }));
    const { container } = render(<ForestPlot rows={unpaired} tau={0.25} />);
    expect(container).toBeEmptyDOMElement();
  });
});

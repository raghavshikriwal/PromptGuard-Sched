import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AGGREGATES } from "../test/fixtures";
import StripPlot, { clippedCount } from "./StripPlot";

const POINTS = new Map([
  [
    "C0",
    [
      { jobId: "a", delta: 0.6, family: "role_confusion" },
      { jobId: "b", delta: 0.05, family: null },
    ],
  ],
  ["C4", [{ jobId: "c", delta: 3, family: "direct_override" }]],
]);

describe("StripPlot", () => {
  it("states the number of jobs and the threshold for screen readers", () => {
    render(<StripPlot rows={AGGREGATES} deltas={POINTS} tau={0.25} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      "Allocation deviation of 3 injected jobs by defense configuration, threshold 0.25",
    );
  });

  it("labels each row with its job count", () => {
    render(<StripPlot rows={AGGREGATES} deltas={POINTS} tau={0.25} />);
    expect(screen.getByText("2 injected job(s)")).toBeInTheDocument();
    expect(screen.getByText("1 injected job(s)")).toBeInTheDocument();
  });

  it("counts dots that lie outside the axis", () => {
    expect(clippedCount(POINTS)).toBe(1);
  });
});

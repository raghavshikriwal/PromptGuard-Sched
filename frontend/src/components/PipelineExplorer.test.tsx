import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PipelineExplorer from "./PipelineExplorer";

describe("PipelineExplorer", () => {
  it("shows the guard stage details by default", () => {
    render(<PipelineExplorer />);
    expect(screen.getByRole("heading", { name: "Input guard" })).toBeInTheDocument();
    expect(screen.getByText("src/guard/classifier.py")).toBeInTheDocument();
  });

  it("marks the three defense stages as off in C0", () => {
    render(<PipelineExplorer />);
    fireEvent.click(screen.getByRole("button", { name: /C0/ }));
    expect(screen.getAllByText("Off in C0")).toHaveLength(3);
  });

  it("shows no off labels in C4", () => {
    render(<PipelineExplorer />);
    expect(screen.queryByText(/^Off in/)).not.toBeInTheDocument();
  });

  it("switches the detail panel when a stage is selected", () => {
    render(<PipelineExplorer />);
    fireEvent.click(screen.getByRole("button", { name: /ILP refinement/ }));
    expect(screen.getByRole("heading", { name: "ILP refinement" })).toBeInTheDocument();
    expect(screen.getByText("src/ilp/refine.py")).toBeInTheDocument();
  });
});

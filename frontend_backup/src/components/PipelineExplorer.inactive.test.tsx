import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PipelineExplorer from "./PipelineExplorer";

describe("PipelineExplorer inactive stage notice", () => {
  it("explains in the detail panel that the selected stage is off in C0", () => {
    render(<PipelineExplorer />);
    fireEvent.click(screen.getByRole("button", { name: /C0/ }));
    expect(screen.getByText("This stage does not run in C0.")).toBeInTheDocument();
  });

  it("shows no such notice when the stage is active", () => {
    render(<PipelineExplorer />);
    expect(screen.queryByText(/does not run in/)).not.toBeInTheDocument();
  });
});

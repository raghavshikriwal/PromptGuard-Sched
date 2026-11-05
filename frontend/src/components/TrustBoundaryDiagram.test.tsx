import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TrustBoundaryDiagram from "./TrustBoundaryDiagram";

describe("TrustBoundaryDiagram", () => {
  it("shows all three trust zones", () => {
    render(<TrustBoundaryDiagram />);
    expect(screen.getByText("Tenant-controlled")).toBeInTheDocument();
    expect(screen.getByText("Touches tenant text")).toBeInTheDocument();
    expect(screen.getByText("Trusted scheduler code")).toBeInTheDocument();
  });

  it("lists what enters the prompt from each side", () => {
    render(<TrustBoundaryDiagram />);
    expect(screen.getByText("Job description")).toBeInTheDocument();
    expect(screen.getByText("Task names")).toBeInTheDocument();
    expect(screen.getByText("System-authored instructions")).toBeInTheDocument();
    expect(screen.getByText("Cluster capacities and telemetry")).toBeInTheDocument();
  });

  it("names the configurations that mark the boundary", () => {
    render(<TrustBoundaryDiagram />);
    expect(screen.getByText(/trust boundary on \(C2 and C4\)/)).toBeInTheDocument();
  });
});

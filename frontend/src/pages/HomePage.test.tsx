import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import HomePage from "./HomePage";

function renderHome() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

describe("HomePage", () => {
  it("shows the project heading", () => {
    renderHome();
    expect(
      screen.getByRole("heading", { name: "PromptGuard-Sched", level: 1 }),
    ).toBeInTheDocument();
  });

  it("shows the exploratory evidence badge", () => {
    renderHome();
    expect(screen.getByText("Exploratory evidence")).toBeInTheDocument();
  });

  it("labels the example as recorded", () => {
    renderHome();
    expect(screen.getByText("Recorded example")).toBeInTheDocument();
    expect(screen.getByText(/Not an aggregate result/)).toBeInTheDocument();
  });

  it("links to the pipeline page", () => {
    renderHome();
    expect(screen.getByRole("link", { name: /pipeline stage by stage/ })).toHaveAttribute(
      "href",
      "/pipeline",
    );
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchStub } from "../test/fixtures";
import HomePage from "./HomePage";

function renderHome() {
  vi.stubGlobal("fetch", fetchStub());
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("HomePage", () => {
  it("shows the project heading", () => {
    renderHome();
    expect(
      screen.getByRole("heading", { name: "PromptGuard-Sched", level: 1 }),
    ).toBeInTheDocument();
  });

  it("shows the evidence level and counts derived from the dataset", async () => {
    renderHome();
    expect(await screen.findByText("Exploratory evidence")).toBeInTheDocument();
    expect(screen.getByText(/4 experiments and 40 scheduling decisions/)).toBeInTheDocument();
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

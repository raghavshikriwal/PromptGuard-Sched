import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchStub } from "../test/fixtures";
import ResultsPage from "./ResultsPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ResultsPage />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ResultsPage", () => {
  it("shows the heading while loading", () => {
    vi.stubGlobal("fetch", fetchStub());
    renderPage();
    expect(screen.getByRole("heading", { name: "Results", level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/Loading results/)).toBeInTheDocument();
  });

  it("renders the ASR table with seeds, denominators and evidence level", async () => {
    vi.stubGlobal("fetch", fetchStub());
    renderPage();
    const table = await screen.findByRole("table");
    const c0 = within(table).getByRole("row", { name: /C0 none/ });
    expect(within(c0).getByText("65.0% ± 20.0")).toBeInTheDocument();
    expect(within(c0).getByText("Exploratory evidence")).toBeInTheDocument();
    const c4 = within(table).getByRole("row", { name: /C4 full/ });
    expect(within(c4).getByText("50.0% ± 10.0 (2 pairs)")).toBeInTheDocument();
  });

  it("changes the numbers when the threshold changes", async () => {
    vi.stubGlobal("fetch", fetchStub());
    renderPage();
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "0.50" }));
    expect(screen.getAllByText("10.0% ± 20.0").length).toBeGreaterThan(0);
  });

  it("discloses missing decisions, empty databases and what is not recorded", async () => {
    vi.stubGlobal("fetch", fetchStub());
    renderPage();
    expect(await screen.findByText(/9 of 10 decisions saved \(1 missing\)/)).toBeInTheDocument();
    expect(
      screen.getByText(/injection_5pct_qwen_seed0.db contains no experiments/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Not recorded: model revision/)).toBeInTheDocument();
    expect(screen.getByText(/What this does not show/)).toBeInTheDocument();
  });

  it("says so when there is nothing to chart", async () => {
    vi.stubGlobal("fetch", fetchStub({ "aggregates.json": [] }));
    renderPage();
    expect(await screen.findByText(/no attack experiments yet/)).toBeInTheDocument();
  });

  it("shows an error with the fix when the export is missing", async () => {
    vi.stubGlobal("fetch", async () => new Response("nope", { status: 404 }));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/canonical_dataset/);
  });

  it("shows an error when the schema has drifted", async () => {
    vi.stubGlobal("fetch", fetchStub({ "manifest.json": { schema_version: 2 } }));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /does not match the expected schema/,
    );
  });
});

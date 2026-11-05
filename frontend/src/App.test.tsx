import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { NAV_ITEMS } from "./lib/nav";

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", async () => new Response("not available in tests", { status: 404 }));
});

describe("App routing", () => {
  it("renders the home heading", () => {
    renderAt("/");
    expect(
      screen.getByRole("heading", { name: "PromptGuard-Sched", level: 1 }),
    ).toBeInTheDocument();
  });

  it.each(NAV_ITEMS.filter((item) => item.path !== "/"))(
    "renders the $label page at $path",
    (item) => {
      renderAt(item.path);
      expect(screen.getByRole("heading", { name: item.label, level: 1 })).toBeInTheDocument();
    },
  );

  it("renders a not-found page for unknown paths", () => {
    renderAt("/nope");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });
});

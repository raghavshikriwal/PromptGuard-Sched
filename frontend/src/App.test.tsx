import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import { NAV_ITEMS } from "./lib/nav";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

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

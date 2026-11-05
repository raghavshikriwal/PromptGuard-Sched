import { NavLink, Outlet } from "react-router-dom";
import { NAV_ITEMS } from "../lib/nav";

const linkClass = ({ isActive }: { isActive: boolean }): string =>
  `rounded-full px-3 py-1.5 text-sm transition-colors ${
    isActive ? "bg-ink text-bg" : "text-muted hover:text-ink"
  }`;

export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 bg-canvas/80 backdrop-blur-xl">
        <div className="mx-auto flex min-h-11 max-w-[1200px] flex-wrap items-center justify-between gap-2 px-6 py-1.5">
          <span className="font-display text-base font-semibold">PromptGuard-Sched</span>
          <nav aria-label="Main" className="flex flex-wrap gap-1">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.path} to={item.path} end={item.path === "/"} className={linkClass}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
      <footer className="bg-canvas py-8 text-xs text-muted">
        <p className="mx-auto max-w-[1200px] px-6">
          Research prototype on simulated workloads. Results are exploratory.
        </p>
      </footer>
    </div>
  );
}

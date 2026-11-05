import { NavLink, Outlet } from "react-router-dom";
import { NAV_ITEMS } from "../lib/nav";

const linkClass = ({ isActive }: { isActive: boolean }): string =>
  `rounded px-3 py-2 text-sm font-medium ${
    isActive ? "bg-ink text-bg" : "text-muted hover:text-ink"
  }`;

export default function Layout() {
  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-5">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-4">
        <span className="font-serif text-xl font-semibold">PromptGuard-Sched</span>
        <nav aria-label="Main" className="flex flex-wrap gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.path} to={item.path} end={item.path === "/"} className={linkClass}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="flex-1 py-10">
        <Outlet />
      </main>
      <footer className="border-t border-line py-4 text-sm text-muted">
        Research prototype on simulated workloads. Results are exploratory.
      </footer>
    </div>
  );
}

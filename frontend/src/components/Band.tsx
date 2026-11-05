import type { ReactNode } from "react";

interface BandProps {
  readonly tone?: "white" | "gray";
  readonly labelledBy?: string;
  readonly children: ReactNode;
}

/** Full-bleed section. Alternating white / gray bands replace dividers. */
export default function Band({ tone = "white", labelledBy, children }: BandProps) {
  return (
    <section
      aria-labelledby={labelledBy}
      className={`${tone === "gray" ? "bg-canvas" : "bg-bg"} py-20 md:py-28`}
    >
      <div className="mx-auto max-w-[1200px] px-6">{children}</div>
    </section>
  );
}

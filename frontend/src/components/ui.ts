import type { CSSProperties } from "react";

/** Shared class strings for the design system, so components stay consistent. */

/** Borderless 28px card. Use `bg-canvas` on white bands and `bg-surface` on canvas bands. */
export const CARD = "rounded-[28px] p-7 md:p-10";

const PILL_BASE =
  "inline-flex items-center justify-center rounded-full px-4 py-[11px] text-[17px] transition-colors";

/** Filled blue pill: the single high-emphasis action per section. */
export const PILL_PRIMARY = `${PILL_BASE} bg-accent text-accent-ink hover:brightness-110`;

/** Quiet pill for toggles and selects; `pressed` fills it with ink. */
export function pillToggle(pressed: boolean): string {
  return `${PILL_BASE} ${pressed ? "bg-ink text-bg" : "bg-wash text-ink hover:brightness-95"}`;
}

export const LINK = "text-link hover:underline";
export const H1 =
  "font-display text-[clamp(2.5rem,7vw,5rem)] font-bold leading-[1.05] tracking-[-0.02em]";
export const H2 = "font-display text-[2rem] font-semibold leading-[1.15] tracking-[0.007em]";

/** Inline style carrying CSS custom properties, e.g. cssVars({ "--hero-delay": "120ms" }). */
export function cssVars(vars: Record<`--${string}`, string>): CSSProperties {
  return vars as CSSProperties;
}

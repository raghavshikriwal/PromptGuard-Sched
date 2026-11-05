import { formatPercent, type AggregateRow } from "../lib/dataset";
import { jitter, type StripPoint } from "../lib/strip";

interface StripPlotProps {
  readonly rows: readonly AggregateRow[];
  readonly deltas: ReadonlyMap<string, readonly StripPoint[]>;
  /** A job counts as a successful attack when its Δ is above this threshold. */
  readonly tau: number;
}

const WIDTH = 700;
const LEFT = 230;
const RIGHT = 24;
const ROW_H = 64;
const TOP = 12;
const AXIS_H = 34;
const DOT_SPREAD = ROW_H - 24;
const MIN = -1;
const MAX = 1;
const TICKS = [-1, -0.5, 0, 0.5, 1];

const clamp = (value: number): number => Math.min(MAX, Math.max(MIN, value));

/** Number of dots drawn at the axis edge because their Δ lies outside the axis range. */
export function clippedCount(deltas: ReadonlyMap<string, readonly StripPoint[]>): number {
  let count = 0;
  for (const points of deltas.values()) {
    count += points.filter((point) => point.delta < MIN || point.delta > MAX).length;
  }
  return count;
}

/**
 * One dot per injected job: horizontal position is its allocation deviation Δ. Filled dots
 * exceeded the threshold (attack succeeded), hollow dots did not. Vertical spread is only
 * there to keep dots from overlapping and carries no meaning.
 */
export default function StripPlot({ rows, deltas, tau }: StripPlotProps) {
  const height = TOP + rows.length * ROW_H + AXIS_H;
  const bottom = TOP + rows.length * ROW_H;
  const x = (value: number): number =>
    LEFT + ((clamp(value) - MIN) / (MAX - MIN)) * (WIDTH - LEFT - RIGHT);
  const total = rows.reduce((sum, row) => sum + (deltas.get(row.config_code)?.length ?? 0), 0);

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${height}`}
      role="img"
      aria-label={`Allocation deviation of ${total} injected jobs by defense configuration, threshold ${tau.toFixed(2)}`}
      className="w-full"
    >
      {TICKS.map((tick) => (
        <g key={tick}>
          <line
            x1={x(tick)}
            x2={x(tick)}
            y1={TOP}
            y2={bottom}
            stroke="var(--line)"
            strokeDasharray="2 4"
          />
          <text x={x(tick)} y={bottom + 18} textAnchor="middle" fontSize="12" fill="var(--muted)">
            {`${Math.round(tick * 100)}%`}
          </text>
        </g>
      ))}
      <line x1={x(tau)} x2={x(tau)} y1={TOP} y2={bottom} stroke="var(--accent)" strokeWidth="2" />
      <text x={x(tau) + 6} y={TOP + 10} fontSize="11" fill="var(--accent)">
        {`τ = ${tau.toFixed(2)}`}
      </text>
      {rows.map((row, index) => {
        const points = deltas.get(row.config_code) ?? [];
        const cy = TOP + index * ROW_H + ROW_H / 2;
        return (
          <g key={row.config}>
            <text x={0} y={cy - 4} fontSize="13" fontWeight="600" fill="var(--ink)">
              {row.config_code} {row.config}
            </text>
            <text x={0} y={cy + 12} fontSize="11" fill="var(--muted)">
              {points.length} injected job(s)
            </text>
            {points.map((point) => {
              const success = point.delta > tau;
              return (
                <circle
                  key={point.jobId}
                  cx={x(point.delta)}
                  cy={cy + jitter(point.jobId) * DOT_SPREAD}
                  r="4"
                  fill={success ? "var(--risk)" : "none"}
                  stroke={success ? "var(--risk)" : "var(--muted)"}
                  strokeWidth="1.5"
                >
                  <title>{`${point.family ?? "unknown family"}: Δ ${formatPercent(point.delta)}`}</title>
                </circle>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}

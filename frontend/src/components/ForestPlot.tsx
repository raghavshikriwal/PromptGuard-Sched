import { formatPaired, type AggregateRow } from "../lib/dataset";

interface ForestPlotProps {
  readonly rows: readonly AggregateRow[];
  /** Threshold the exporter computed the paired reductions at (the manifest's default). */
  readonly tau: number;
}

type PairedRow = AggregateRow & {
  readonly paired_asr_vs_c0: NonNullable<AggregateRow["paired_asr_vs_c0"]>;
};

const WIDTH = 700;
const LEFT = 230;
const RIGHT = 24;
const ROW_H = 52;
const TOP = 12;
const AXIS_H = 52;
const TICKS = [-1, -0.5, 0, 0.5, 1];

const clamp = (value: number): number => Math.min(1, Math.max(-1, value));

/** Rows that have a paired reduction vs C0 (C0 itself and unpaired configs have none). */
export function pairedRows(rows: readonly AggregateRow[]): PairedRow[] {
  return rows.filter(
    (row): row is PairedRow =>
      row.paired_asr_vs_c0 !== null && row.paired_asr_vs_c0.mean_reduction !== null,
  );
}

/**
 * Forest plot of the paired ASR reduction versus C0: dot = mean over seed pairs, bar = 95% CI.
 * Right of the zero line is better than no defense. A bar that crosses zero means the data
 * cannot tell the defense apart from no defense.
 */
export default function ForestPlot({ rows, tau }: ForestPlotProps) {
  const data = pairedRows(rows);
  if (data.length === 0) return null;

  const height = TOP + data.length * ROW_H + AXIS_H;
  const bottom = TOP + data.length * ROW_H;
  const x = (value: number): number => LEFT + ((clamp(value) + 1) / 2) * (WIDTH - LEFT - RIGHT);
  const summary = data.map((row) => `${row.config_code} ${formatPaired(row.paired_asr_vs_c0)}`);

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${height}`}
      role="img"
      aria-label={`Reduction in attack success rate versus C0 at threshold ${tau.toFixed(2)}: ${summary.join("; ")}`}
      className="w-full"
    >
      {TICKS.map((tick) => (
        <g key={tick}>
          <line
            x1={x(tick)}
            x2={x(tick)}
            y1={TOP}
            y2={bottom}
            stroke={tick === 0 ? "var(--ink)" : "var(--line)"}
            strokeDasharray={tick === 0 ? undefined : "2 4"}
          />
          <text x={x(tick)} y={bottom + 18} textAnchor="middle" fontSize="12" fill="var(--muted)">
            {`${Math.round(tick * 100)}%`}
          </text>
        </g>
      ))}
      <text x={x(-1)} y={bottom + 40} fontSize="12" fill="var(--muted)">
        Worse than C0
      </text>
      <text x={x(1)} y={bottom + 40} textAnchor="end" fontSize="12" fill="var(--muted)">
        Better than C0 (at τ = {tau.toFixed(2)})
      </text>
      {data.map((row, index) => {
        const paired = row.paired_asr_vs_c0;
        const mean = paired.mean_reduction ?? 0;
        const half = paired.half_width;
        const cy = TOP + index * ROW_H + ROW_H / 2;
        return (
          <g key={row.config}>
            <text x={0} y={cy - 4} fontSize="13" fontWeight="600" fill="var(--ink)">
              {row.config_code} {row.config}
            </text>
            <text x={0} y={cy + 12} fontSize="11" fill="var(--muted)">
              {formatPaired(paired)}
            </text>
            {half !== null ? (
              <line
                x1={x(mean - half)}
                x2={x(mean + half)}
                y1={cy}
                y2={cy}
                stroke="var(--accent)"
                strokeWidth="3"
                strokeLinecap="round"
              />
            ) : null}
            <circle cx={x(mean)} cy={cy} r="6" fill="var(--accent)">
              <title>{`${row.config_code}: ${formatPaired(paired)}`}</title>
            </circle>
          </g>
        );
      })}
    </svg>
  );
}

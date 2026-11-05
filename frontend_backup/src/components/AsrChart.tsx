import { formatMeanCi, formatPercent, metricKey, type AggregateRow } from "../lib/dataset";

interface AsrChartProps {
  readonly rows: readonly AggregateRow[];
  readonly tau: number;
}

const WIDTH = 700;
const LEFT = 230;
const RIGHT = 24;
const ROW_H = 48;
const TOP = 12;
const AXIS_H = 34;
const TICKS = [0, 0.25, 0.5, 0.75, 1];

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

/**
 * Attack success rate per defense configuration: dot = mean over seeds, bar = 95% CI,
 * hollow squares = individual seeds. The row label always carries the number of seeds and
 * injected jobs, and the same numbers are repeated in a table next to the chart.
 */
export default function AsrChart({ rows, tau }: AsrChartProps) {
  const key = metricKey(tau);
  const height = TOP + rows.length * ROW_H + AXIS_H;
  const x = (value: number): number => LEFT + clamp01(value) * (WIDTH - LEFT - RIGHT);
  const summary = rows
    .map((row) => `${row.config_code} ${formatMeanCi(row.metrics[key])}`)
    .join("; ");

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${height}`}
      role="img"
      aria-label={`Attack success rate at threshold ${tau.toFixed(2)}: ${summary}`}
      className="w-full max-w-3xl"
    >
      {TICKS.map((tick) => (
        <g key={tick}>
          <line
            x1={x(tick)}
            x2={x(tick)}
            y1={TOP}
            y2={TOP + rows.length * ROW_H}
            stroke="var(--line)"
          />
          <text
            x={x(tick)}
            y={TOP + rows.length * ROW_H + 18}
            textAnchor="middle"
            fontSize="12"
            fill="var(--muted)"
          >
            {formatPercent(tick).replace(".0", "")}
          </text>
        </g>
      ))}
      {rows.map((row, index) => {
        const metric = row.metrics[key];
        const cy = TOP + index * ROW_H + ROW_H / 2;
        const injected = row.injected_per_run.join(", ");
        return (
          <g key={row.config}>
            <text x={0} y={cy - 4} fontSize="13" fontWeight="600" fill="var(--ink)">
              {row.config_code} {row.config}
            </text>
            <text x={0} y={cy + 12} fontSize="11" fill="var(--muted)">
              {row.seeds.length} seed(s) · injected/run: {injected}
            </text>
            {metric && metric.mean !== null ? (
              <>
                {metric.half_width !== null ? (
                  <line
                    x1={x(metric.mean - metric.half_width)}
                    x2={x(metric.mean + metric.half_width)}
                    y1={cy}
                    y2={cy}
                    stroke="var(--ink)"
                    strokeWidth="2"
                  />
                ) : null}
                {metric.points.map((point) =>
                  point.value === null ? null : (
                    <rect
                      key={point.experiment_id}
                      x={x(point.value) - 4}
                      y={cy - 4}
                      width="8"
                      height="8"
                      fill="none"
                      stroke="var(--risk)"
                      strokeWidth="1.5"
                    >
                      <title>{`seed ${point.seed}: ${formatPercent(point.value)} of ${point.n} injected`}</title>
                    </rect>
                  ),
                )}
                <circle cx={x(metric.mean)} cy={cy} r="6" fill="var(--ink)">
                  <title>{`mean ${formatMeanCi(metric)}`}</title>
                </circle>
              </>
            ) : (
              <text x={LEFT + 8} y={cy + 4} fontSize="12" fill="var(--muted)">
                no data
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

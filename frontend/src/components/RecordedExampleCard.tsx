import { RECORDED_EXAMPLE } from "../lib/evidence";
import { CARD, cssVars } from "./ui";

const PERCENT = 100;
const STAGGER_MS = 120;

function toPercent(share: number): string {
  return `${share * PERCENT}%`;
}

function Bar({ share, tone, index }: { share: number; tone: string; index: number }) {
  return (
    <div aria-hidden="true" className="h-2 overflow-hidden rounded-full bg-wash">
      <div
        className={`bar-grow h-2 rounded-full ${tone}`}
        style={{
          width: toPercent(share),
          ...cssVars({ "--reveal-delay": `${index * STAGGER_MS}ms` }),
        }}
      />
    </div>
  );
}

export default function RecordedExampleCard() {
  const example = RECORDED_EXAMPLE;
  return (
    <div className={`${CARD} bg-surface`}>
      <p className="inline-block rounded-full bg-wash px-3 py-1 text-sm text-muted">
        Recorded example
      </p>
      <p className="mt-3 text-sm text-muted">{example.sourceNote}</p>

      <ol className="mt-8 space-y-3">
        <li>
          The guard scored the job text <strong>{example.guardScore}</strong>.
        </li>
        <li>
          The model proposed a share of <strong>{example.proposedShare}</strong> for every resource.
        </li>
        <li>
          The anomaly cap limited the relative deviation to about{" "}
          <strong>{example.cappedMaxDeviation}</strong>.
        </li>
        <li>
          ILP refinement finished with status <strong>{example.solverStatus}</strong>. Final shares
          in {example.configCode}:
        </li>
      </ol>

      <table className="mt-8 w-full text-sm">
        <thead>
          <tr className="text-left text-muted">
            <th className="py-2 pr-4 font-medium">Resource</th>
            <th className="py-2 pr-4 font-medium">Proposed</th>
            <th className="py-2 font-medium">Final</th>
          </tr>
        </thead>
        <tbody>
          {example.finalShares.map((item, index) => (
            <tr key={item.resource}>
              <td className="py-3 pr-4 font-medium">{item.resource}</td>
              <td className="py-3 pr-4">
                <Bar share={example.proposedShare} tone="bg-muted" index={index} />
                <span className="text-muted">{example.proposedShare}</span>
              </td>
              <td className="py-3">
                <Bar share={item.share} tone="bg-accent" index={index} />
                <span>{item.display}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

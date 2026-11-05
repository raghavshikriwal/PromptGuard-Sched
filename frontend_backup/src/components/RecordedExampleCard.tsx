import { RECORDED_EXAMPLE } from "../lib/evidence";

const PERCENT = 100;

function toPercent(share: number): string {
  return `${share * PERCENT}%`;
}

export default function RecordedExampleCard() {
  const example = RECORDED_EXAMPLE;
  return (
    <div className="rounded border border-line bg-surface p-5">
      <p className="inline-block rounded border border-line px-2 py-0.5 text-sm text-muted">
        Recorded example
      </p>
      <p className="mt-2 text-sm text-muted">{example.sourceNote}</p>

      <ol className="mt-5 space-y-2">
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

      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="text-left text-muted">
            <th className="py-2 pr-3 font-medium">Resource</th>
            <th className="py-2 pr-3 font-medium">Proposed</th>
            <th className="py-2 font-medium">Final</th>
          </tr>
        </thead>
        <tbody>
          {example.finalShares.map((item) => (
            <tr key={item.resource} className="border-t border-line">
              <td className="py-2 pr-3 font-medium">{item.resource}</td>
              <td className="py-2 pr-3">
                <div aria-hidden="true" className="h-2 rounded bg-line">
                  <div
                    className="h-2 rounded bg-muted"
                    style={{ width: toPercent(example.proposedShare) }}
                  />
                </div>
                <span className="text-muted">{example.proposedShare}</span>
              </td>
              <td className="py-2">
                <div aria-hidden="true" className="h-2 rounded bg-line">
                  <div className="h-2 rounded bg-safe" style={{ width: toPercent(item.share) }} />
                </div>
                <span>{item.display}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

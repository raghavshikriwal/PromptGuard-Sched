import { useDataset } from "../hooks/useDataset";
import { EVIDENCE_LEVEL_LABEL } from "../lib/evidence";
import { deriveEvidenceFacts, deriveEvidenceLevel } from "../lib/evidenceFacts";
import { CARD } from "./ui";

/** Evidence status for the whole site. Every line is computed from the exported dataset. */
export default function EvidenceBadge() {
  const { data, error, isPending } = useDataset();
  const level = data ? deriveEvidenceLevel(data.aggregates) : null;

  return (
    <div className={`${CARD} bg-canvas`} aria-live="polite">
      {isPending ? <p className="text-muted">Loading evidence status…</p> : null}
      {error ? (
        <p role="alert" className="text-risk">
          Evidence status is unavailable: {error.message}
        </p>
      ) : null}
      {data ? (
        <>
          <p className="text-sm font-medium text-risk">
            {level ? EVIDENCE_LEVEL_LABEL[level] : "No attack experiments yet"}
          </p>
          <ul className="mt-4 space-y-2 text-muted">
            {deriveEvidenceFacts(data).map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

import { CURRENT_EVIDENCE_LEVEL, EVIDENCE_FACTS, EVIDENCE_LEVEL_LABEL } from "../lib/evidence";
import { CARD } from "./ui";

export default function EvidenceBadge() {
  return (
    <div className={`${CARD} bg-canvas`}>
      <p className="text-sm font-medium text-risk">
        {EVIDENCE_LEVEL_LABEL[CURRENT_EVIDENCE_LEVEL]}
      </p>
      <ul className="mt-4 space-y-2 text-muted">
        {EVIDENCE_FACTS.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
    </div>
  );
}

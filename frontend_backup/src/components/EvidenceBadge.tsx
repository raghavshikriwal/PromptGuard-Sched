import { CURRENT_EVIDENCE_LEVEL, EVIDENCE_FACTS, EVIDENCE_LEVEL_LABEL } from "../lib/evidence";

export default function EvidenceBadge() {
  return (
    <div className="rounded border border-warn p-4">
      <p className="font-medium text-warn">{EVIDENCE_LEVEL_LABEL[CURRENT_EVIDENCE_LEVEL]}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
        {EVIDENCE_FACTS.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
    </div>
  );
}

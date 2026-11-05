import { CARD } from "./ui";
import { ZONE_DOT, ZONE_LABEL } from "../lib/pipeline";
import {
  PROMPT_INPUT_GROUPS,
  ZONE_ORDER,
  boundaryConfigCodes,
  stagesByZone,
} from "../lib/trustBoundary";

export default function TrustBoundaryDiagram() {
  const boundaryCodes = boundaryConfigCodes().join(" and ");

  return (
    <div>
      <ol className="space-y-1" aria-label="Trust zones">
        {ZONE_ORDER.map((zone, index) => (
          <li key={zone}>
            <div className={`${CARD} bg-canvas`}>
              <p className="flex items-center gap-2 font-medium">
                <span aria-hidden="true" className={`h-3 w-3 rounded-full ${ZONE_DOT[zone]}`} />
                {ZONE_LABEL[zone]}
              </p>
              <ul className="mt-3 flex flex-wrap gap-2">
                {stagesByZone(zone).map((stage) => (
                  <li key={stage.id} className="rounded-full bg-wash px-3 py-1 text-sm">
                    {stage.name}
                  </li>
                ))}
              </ul>
            </div>
            {index < ZONE_ORDER.length - 1 && (
              <svg
                aria-hidden="true"
                viewBox="0 0 16 20"
                className="ml-6 mt-1 h-5 w-4 text-muted"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M8 0 V16 M2 10 L8 17 L14 10" />
              </svg>
            )}
          </li>
        ))}
      </ol>

      <div className="mt-6 grid gap-5 md:grid-cols-2">
        {PROMPT_INPUT_GROUPS.map((group) => (
          <div key={group.zone} className={`${CARD} bg-canvas`}>
            <h3 className="flex items-center gap-2 font-medium">
              <span aria-hidden="true" className={`h-3 w-3 rounded-full ${ZONE_DOT[group.zone]}`} />
              {group.title}
            </h3>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
              {group.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <p className="mt-6 max-w-prose text-sm text-muted">
        With the trust boundary on ({boundaryCodes}), these two groups are marked as separate parts
        of the prompt. In every other configuration, tenant text enters the prompt without a marked
        boundary.
      </p>
    </div>
  );
}

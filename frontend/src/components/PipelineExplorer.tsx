import { useState } from "react";
import {
  DEFAULT_CONFIG_ID,
  DEFAULT_STAGE_ID,
  DEFENSE_CONFIGS,
  PIPELINE_STAGES,
  ZONE_LABEL,
  getConfig,
  isStageActive,
  type DefenseConfigId,
  type TrustZone,
} from "../lib/pipeline";

const ZONE_DOT: Record<TrustZone, string> = {
  tenant: "bg-risk",
  mixed: "bg-warn",
  trusted: "bg-safe",
};

export default function PipelineExplorer() {
  const [configId, setConfigId] = useState<DefenseConfigId>(DEFAULT_CONFIG_ID);
  const [stageId, setStageId] = useState<string>(DEFAULT_STAGE_ID);

  const config = getConfig(configId);
  const stage = PIPELINE_STAGES.find((item) => item.id === stageId);

  return (
    <div>
      <div role="group" aria-label="Defense configuration" className="flex flex-wrap gap-2">
        {DEFENSE_CONFIGS.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={item.id === configId}
            onClick={() => setConfigId(item.id)}
            className={`rounded border border-line px-3 py-2 text-sm ${
              item.id === configId ? "bg-ink text-bg" : "bg-surface"
            }`}
          >
            {item.code}: {item.label}
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-6 md:grid-cols-[1fr_1.1fr]">
        <ol className="space-y-2" aria-label="Pipeline stages">
          {PIPELINE_STAGES.map((item) => {
            const active = isStageActive(item, configId);
            const selected = item.id === stageId;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => setStageId(item.id)}
                  className={`flex w-full items-center gap-3 rounded border px-3 py-3 text-left ${
                    selected ? "border-ink bg-surface" : "border-line"
                  } ${active ? "" : "opacity-50"}`}
                >
                  <span
                    aria-hidden="true"
                    className={`h-3 w-3 shrink-0 rounded-full ${ZONE_DOT[item.zone]}`}
                  />
                  <span className="flex-1 font-medium">{item.name}</span>
                  {!active && <span className="text-sm text-muted">Off in {config.code}</span>}
                </button>
              </li>
            );
          })}
        </ol>

        <div className="rounded border border-line bg-surface p-5" aria-live="polite">
          {stage ? (
            <>
              <h2 className="font-serif text-2xl font-semibold">{stage.name}</h2>
              <p className="mt-1 flex items-center gap-2 text-sm text-muted">
                <span
                  aria-hidden="true"
                  className={`h-3 w-3 rounded-full ${ZONE_DOT[stage.zone]}`}
                />
                {ZONE_LABEL[stage.zone]}
              </p>
              {!isStageActive(stage, configId) && (
                <p className="mt-3 rounded border border-line px-3 py-2 text-sm text-muted">
                  This stage does not run in {config.code}.
                </p>
              )}
              <p className="mt-4 max-w-prose">{stage.summary}</p>
              <dl className="mt-4 space-y-3 text-sm">
                <div>
                  <dt className="text-muted">Takes in</dt>
                  <dd>{stage.input}</dd>
                </div>
                <div>
                  <dt className="text-muted">Produces</dt>
                  <dd>{stage.output}</dd>
                </div>
                {stage.codePath && (
                  <div>
                    <dt className="text-muted">Code</dt>
                    <dd>
                      <code>{stage.codePath}</code>
                    </dd>
                  </div>
                )}
              </dl>
            </>
          ) : (
            <p className="text-muted">Select a stage to see what it does.</p>
          )}
        </div>
      </div>
    </div>
  );
}

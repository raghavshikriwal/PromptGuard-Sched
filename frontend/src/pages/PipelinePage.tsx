import Band from "../components/Band";
import PipelineExplorer from "../components/PipelineExplorer";
import Reveal from "../components/Reveal";
import TrustBoundaryDiagram from "../components/TrustBoundaryDiagram";
import { H1, H2, cssVars } from "../components/ui";

export default function PipelinePage() {
  return (
    <>
      <Band>
        <h1 className={`${H1} hero-in`}>Pipeline</h1>
        <p
          className="hero-in mt-6 max-w-prose text-[21px] leading-snug text-muted"
          style={cssVars({ "--hero-delay": "120ms" })}
        >
          How one job moves through the scheduler. Pick a defense configuration to see which stages
          run, then select a stage for details. The LLM only proposes an allocation; the stages
          after it decide what is accepted.
        </p>
        <p
          className="hero-in mt-3 max-w-prose text-sm text-muted"
          style={cssVars({ "--hero-delay": "200ms" })}
        >
          This diagram describes the code structure. It does not run a model.
        </p>
      </Band>

      <Band tone="gray">
        <PipelineExplorer />
      </Band>

      <Band labelledBy="boundary-heading">
        <Reveal>
          <h2 id="boundary-heading" className={H2}>
            Where tenant text enters
          </h2>
          <p className="mt-3 max-w-prose text-muted">
            Tenants control free text only. Everything that decides what is accepted sits in trusted
            scheduler code.
          </p>
        </Reveal>
        <Reveal className="mt-10" delay={100}>
          <TrustBoundaryDiagram />
        </Reveal>
      </Band>
    </>
  );
}

import PipelineExplorer from "../components/PipelineExplorer";

export default function PipelinePage() {
  return (
    <section>
      <h1 className="font-serif text-3xl font-semibold">Pipeline</h1>
      <p className="mt-3 max-w-prose text-muted">
        How one job moves through the scheduler. Pick a defense configuration to see which stages
        run, then select a stage for details. The LLM only proposes an allocation; the stages after
        it decide what is accepted.
      </p>
      <p className="mt-2 max-w-prose text-sm text-muted">
        This diagram describes the code structure. It does not run a model.
      </p>
      <div className="mt-8">
        <PipelineExplorer />
      </div>
    </section>
  );
}

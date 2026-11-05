import { Link } from "react-router-dom";
import EvidenceBadge from "../components/EvidenceBadge";
import RecordedExampleCard from "../components/RecordedExampleCard";

export default function HomePage() {
  return (
    <div className="space-y-10">
      <section>
        <h1 className="font-serif text-4xl font-semibold leading-tight">PromptGuard-Sched</h1>
        <p className="mt-3 max-w-prose text-lg text-muted">
          Can a tenant's job description talk an LLM scheduler into giving it more than its fair
          share, and do the defenses stop that without hurting everyone else?
        </p>
        <div className="mt-6 max-w-prose">
          <EvidenceBadge />
        </div>
      </section>

      <section aria-labelledby="example-heading">
        <h2 id="example-heading" className="font-serif text-2xl font-semibold">
          What a defense does to one job
        </h2>
        <p className="mt-2 max-w-prose text-muted">
          A real record from the full defense configuration, shown as stored.
        </p>
        <div className="mt-4 max-w-2xl">
          <RecordedExampleCard />
        </div>
      </section>

      <section aria-labelledby="explore-heading">
        <h2 id="explore-heading" className="font-serif text-2xl font-semibold">
          Explore
        </h2>
        <ul className="mt-3 flex flex-wrap gap-3">
          <li>
            <Link className="underline" to="/pipeline">
              See the pipeline stage by stage
            </Link>
          </li>
          <li>
            <Link className="underline" to="/research">
              Read the threat model and limits
            </Link>
          </li>
        </ul>
      </section>
    </div>
  );
}

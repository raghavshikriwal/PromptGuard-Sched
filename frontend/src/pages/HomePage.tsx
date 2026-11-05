import { Link } from "react-router-dom";
import Band from "../components/Band";
import EvidenceBadge from "../components/EvidenceBadge";
import RecordedExampleCard from "../components/RecordedExampleCard";
import Reveal from "../components/Reveal";
import { H1, H2, LINK, PILL_PRIMARY, cssVars } from "../components/ui";

export default function HomePage() {
  return (
    <>
      <Band>
        <div className="mx-auto max-w-4xl text-center">
          <h1 className={`${H1} hero-in`}>PromptGuard-Sched</h1>
          <p
            className="hero-in mx-auto mt-6 max-w-[34ch] text-[21px] leading-snug text-muted"
            style={cssVars({ "--hero-delay": "150ms" })}
          >
            Can a tenant's job description talk an LLM scheduler into giving it more than its fair
            share, and do the defenses stop that without hurting everyone else?
          </p>
          <div
            className="hero-in mt-8 flex flex-wrap justify-center gap-3"
            style={cssVars({ "--hero-delay": "300ms" })}
          >
            <Link className={PILL_PRIMARY} to="/results">
              See the results
            </Link>
            <Link className={`${LINK} inline-flex items-center px-3 text-[17px]`} to="/pipeline">
              Explore the pipeline &rsaquo;
            </Link>
          </div>
        </div>
        <Reveal className="mx-auto mt-16 max-w-2xl">
          <EvidenceBadge />
        </Reveal>
      </Band>

      <Band tone="gray" labelledBy="example-heading">
        <Reveal>
          <h2 id="example-heading" className={H2}>
            What a defense does to one job
          </h2>
          <p className="mt-3 max-w-prose text-muted">
            A real record from the full defense configuration, shown as stored.
          </p>
        </Reveal>
        <Reveal className="mt-10 max-w-2xl" delay={100}>
          <RecordedExampleCard />
        </Reveal>
      </Band>

      <Band labelledBy="explore-heading">
        <Reveal>
          <h2 id="explore-heading" className={H2}>
            Explore
          </h2>
          <ul className="mt-6 space-y-3 text-[21px]">
            <li>
              <Link className={LINK} to="/pipeline">
                See the pipeline stage by stage &rsaquo;
              </Link>
            </li>
            <li>
              <Link className={LINK} to="/research">
                Read the threat model and limits &rsaquo;
              </Link>
            </li>
          </ul>
        </Reveal>
      </Band>
    </>
  );
}

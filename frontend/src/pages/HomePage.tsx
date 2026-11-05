export default function HomePage() {
  return (
    <section>
      <h1 className="font-serif text-4xl font-semibold leading-tight">PromptGuard-Sched</h1>
      <p className="mt-3 max-w-prose text-muted">
        Can a tenant's job description talk an LLM scheduler into giving it more than its fair
        share, and do the defenses stop that without hurting everyone else?
      </p>
      <p className="mt-4 inline-block rounded border border-warn px-3 py-1 text-sm text-warn">
        Exploratory evidence. Intervals are wide.
      </p>
    </section>
  );
}

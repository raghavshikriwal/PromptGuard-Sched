interface PlaceholderPageProps {
  readonly title: string;
  readonly summary: string;
}

export default function PlaceholderPage({ title, summary }: PlaceholderPageProps) {
  return (
    <section>
      <h1 className="font-serif text-3xl font-semibold">{title}</h1>
      <p className="mt-3 max-w-prose text-muted">{summary}</p>
      <p className="mt-4 text-sm text-muted">This page is not built yet.</p>
    </section>
  );
}

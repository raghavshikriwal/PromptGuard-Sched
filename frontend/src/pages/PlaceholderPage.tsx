import Band from "../components/Band";
import { H1 } from "../components/ui";

interface PlaceholderPageProps {
  readonly title: string;
  readonly summary: string;
}

export default function PlaceholderPage({ title, summary }: PlaceholderPageProps) {
  return (
    <Band>
      <h1 className={H1}>{title}</h1>
      <p className="mt-6 max-w-prose text-[21px] leading-snug text-muted">{summary}</p>
      <p className="mt-4 text-sm text-muted">This page is not built yet.</p>
    </Band>
  );
}

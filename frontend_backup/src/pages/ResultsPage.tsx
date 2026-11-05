import { useState } from "react";
import AsrChart from "../components/AsrChart";
import { useDataset } from "../hooks/useDataset";
import {
  formatMeanCi,
  formatPaired,
  groupCampaigns,
  metricKey,
  type Campaign,
  type Dataset,
} from "../lib/dataset";
import { EVIDENCE_LEVEL_LABEL } from "../lib/evidence";

function CampaignView({ campaign, dataset }: { campaign: Campaign; dataset: Dataset }) {
  const taus = dataset.manifest.thresholds;
  const [tau, setTau] = useState<number>(dataset.manifest.tau_default);
  const key = metricKey(tau);
  const caveats = campaign.rows.flatMap((row) =>
    row.caveats.map((text) => `${row.config_code}: ${text}`),
  );

  return (
    <div className="mt-6 space-y-6">
      <div
        role="group"
        aria-label="Success threshold"
        className="flex flex-wrap items-center gap-2"
      >
        <span className="text-sm text-muted">Success threshold τ (Δ must exceed):</span>
        {taus.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={value === tau}
            onClick={() => setTau(value)}
            className={`rounded border border-line px-3 py-1 text-sm ${
              value === tau ? "bg-ink text-bg" : "bg-surface"
            }`}
          >
            {value.toFixed(2)}
          </button>
        ))}
      </div>

      <AsrChart rows={campaign.rows} tau={tau} />

      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <caption className="sr-only">Attack success rate by defense configuration</caption>
          <thead className="border-b-2 border-ink">
            <tr>
              <th scope="col" className="py-2 pr-3">
                Config
              </th>
              <th scope="col" className="py-2 pr-3">
                ASR (mean ± 95% CI)
              </th>
              <th scope="col" className="py-2 pr-3">
                Seeds
              </th>
              <th scope="col" className="py-2 pr-3">
                Injected per run
              </th>
              <th scope="col" className="py-2 pr-3">
                Reduction vs C0
              </th>
              <th scope="col" className="py-2">
                Evidence
              </th>
            </tr>
          </thead>
          <tbody>
            {campaign.rows.map((row) => (
              <tr key={row.config} className="border-b border-line">
                <th scope="row" className="py-2 pr-3 font-medium">
                  {row.config_code} {row.config}
                </th>
                <td className="py-2 pr-3">{formatMeanCi(row.metrics[key])}</td>
                <td className="py-2 pr-3">{row.seeds.join(", ")}</td>
                <td className="py-2 pr-3">{row.injected_per_run.join(", ")}</td>
                <td className="py-2 pr-3">{formatPaired(row.paired_asr_vs_c0)}</td>
                <td className="py-2">{EVIDENCE_LEVEL_LABEL[row.evidence]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-muted">
        Intervals are Student-t over seeds. With few seeds they can extend below 0% or above 100%;
        the chart clips them at the axis, the table does not.
      </p>

      <aside className="rounded border border-warn p-4">
        <h3 className="font-medium text-warn">What this does not show</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
          <li>Jobs come from the trace simulator, not from a real cluster.</li>
          <li>
            Model: {[...new Set(campaign.rows.map((row) => row.model_id))].join(", ")}. Results do
            not transfer to other models.
          </li>
          {caveats.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

function IntegrityView({ dataset }: { dataset: Dataset }) {
  const { integrity, manifest } = dataset;
  return (
    <section aria-labelledby="integrity-heading" className="mt-12">
      <h2 id="integrity-heading" className="font-serif text-2xl font-semibold">
        Data integrity
      </h2>
      <p className="mt-2 text-sm text-muted">
        {manifest.counts.experiments_canonical} experiments from {manifest.counts.databases}{" "}
        databases, {manifest.counts.decisions} scheduling decisions. Dataset hash{" "}
        <code>{manifest.dataset_sha256.slice(0, 12)}</code>, generated {manifest.generated_at}.
      </p>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
        {integrity.missing_decisions.map((item) => (
          <li key={item.experiment_id}>
            {item.config} seed {item.seed} in {item.database}: {item.present} of {item.expected}{" "}
            decisions saved ({item.missing} missing).
          </li>
        ))}
        {integrity.databases_without_experiments.map((name) => (
          <li key={name}>{name} contains no experiments.</li>
        ))}
        {integrity.skipped_databases.map((item) => (
          <li key={item.database}>
            {item.database} was skipped ({item.reason}).
          </li>
        ))}
        {integrity.smoke_test_experiments_excluded_from_aggregates.length > 0 ? (
          <li>
            {integrity.smoke_test_experiments_excluded_from_aggregates.length} smoke-test run(s) are
            kept out of every aggregate.
          </li>
        ) : null}
        {integrity.not_recorded_in_databases.map((text) => (
          <li key={text}>Not recorded: {text}.</li>
        ))}
      </ul>
    </section>
  );
}

function ResultsBody({ dataset }: { dataset: Dataset }) {
  const campaigns = groupCampaigns(dataset.aggregates);
  const [selected, setSelected] = useState<string | undefined>(campaigns[0]?.groupId);
  const campaign = campaigns.find((item) => item.groupId === selected) ?? campaigns[0];

  if (!campaign) {
    return (
      <p className="mt-6 text-muted">
        The export contains no attack experiments yet, so there is nothing to chart.
      </p>
    );
  }
  return (
    <>
      <div className="mt-6">
        <label htmlFor="campaign" className="mr-2 text-sm text-muted">
          Campaign (one database, one injection ratio)
        </label>
        <select
          id="campaign"
          value={campaign.groupId}
          onChange={(event) => setSelected(event.target.value)}
          className="rounded border border-line bg-surface px-2 py-1 text-sm"
        >
          {campaigns.map((item) => (
            <option key={item.groupId} value={item.groupId}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      <CampaignView key={campaign.groupId} campaign={campaign} dataset={dataset} />
    </>
  );
}

export default function ResultsPage() {
  const { data, error, isPending } = useDataset();
  return (
    <section>
      <h1 className="font-serif text-3xl font-semibold">Results</h1>
      <p className="mt-3 max-w-prose text-muted">
        Attack success rate (ASR) per defense configuration. Every figure is read from the exported
        experiment databases, with the number of seeds and injected jobs beside it.
      </p>
      {isPending ? <p className="mt-6 text-muted">Loading results…</p> : null}
      {error ? (
        <p role="alert" className="mt-6 rounded border border-risk p-4 text-risk">
          {error.message}
        </p>
      ) : null}
      {data ? (
        <>
          <ResultsBody dataset={data} />
          <IntegrityView dataset={data} />
        </>
      ) : null}
    </section>
  );
}

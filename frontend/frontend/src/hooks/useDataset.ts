import { useQuery } from "@tanstack/react-query";
import {
  aggregateRowSchema,
  experimentSchema,
  integritySchema,
  manifestSchema,
  parseDecisions,
  parseJson,
  type Dataset,
} from "../lib/dataset";
import { z } from "zod";

async function fetchJson(file: string): Promise<unknown> {
  const url = `${import.meta.env.BASE_URL}data/${file}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `Could not load ${file} (HTTP ${response.status}). Run: python -m eval.export.canonical_dataset`,
    );
  }
  return response.json();
}

export async function loadDataset(): Promise<Dataset> {
  const [manifest, aggregates, experiments, integrity] = await Promise.all([
    fetchJson("manifest.json"),
    fetchJson("aggregates.json"),
    fetchJson("experiments.json"),
    fetchJson("integrity.json"),
  ]);
  return {
    manifest: parseJson(manifestSchema, "manifest.json", manifest),
    aggregates: parseJson(z.array(aggregateRowSchema), "aggregates.json", aggregates),
    experiments: parseJson(z.array(experimentSchema), "experiments.json", experiments),
    integrity: parseJson(integritySchema, "integrity.json", integrity),
  };
}

export function useDataset() {
  return useQuery({ queryKey: ["dataset"], queryFn: loadDataset, staleTime: Infinity });
}

/** Per-job rows are the largest file, so they load only when a page asks for them. */
export function useDecisions() {
  return useQuery({
    queryKey: ["decisions"],
    queryFn: async () => parseDecisions(await fetchJson("decisions.json")),
    staleTime: Infinity,
  });
}

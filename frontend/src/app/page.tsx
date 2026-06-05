"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import JobExecutionPanel from "@/components/pipelines/JobExecutionPanel";
import { usePipeline } from "@/components/pipelines/PipelineContext";
import { getPipelineYaml, listPipelineYamls } from "@/lib/api";
import type { YamlSummary } from "@/types";

export default function HomePage() {
  const { yamlName, yamlContent, pipelineNames, setYamlName, setYamlContent, setPipelineNames, setStatus } =
    usePipeline();
  const [yamls, setYamls] = useState<YamlSummary[]>([]);

  useEffect(() => {
    listPipelineYamls()
      .then((list) => {
        setYamls(list);
        // First load: nothing parsed yet, so auto-select a YAML and load its
        // content into shared state — otherwise Validation/Job pages open empty.
        if (!yamlContent && list.length) {
          const initial = list.find((document) => document.name === yamlName) ?? list[0];
          void selectYaml(initial.name);
        }
      })
      .catch((error: Error) => setStatus(error.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectYaml(name: string) {
    if (!name) return;
    try {
      const document = await getPipelineYaml(name);
      setYamlName(document.name);
      setYamlContent(document.content);
      setPipelineNames(document.pipelines);
      setStatus(
        document.is_valid ? `Loaded ${document.name}` : `Loaded ${document.name}; not a runnable pipeline YAML`
      );
    } catch (error) {
      setStatus((error as Error).message);
    }
  }

  return (
    <div className="grid gap-4 p-5">
      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="grid gap-1 text-xs font-semibold text-slate-500">
            Pipeline YAML
            <select
              className="h-9 min-w-64 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
              value={yamlName}
              onChange={(event) => selectYaml(event.target.value)}
            >
              <option value="" disabled>
                Select a YAML…
              </option>
              {yamls.map((document) => (
                <option key={document.name} value={document.name}>
                  {document.name}
                  {document.is_valid ? "" : " (not runnable)"}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/validation"
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
            >
              Validate →
            </Link>
            <Link
              href="/storage"
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
            >
              Storage
            </Link>
          </div>
        </div>
        {pipelineNames.length === 0 ? (
          <p className="text-xs text-slate-500">
            No pipelines loaded yet. Select a YAML above or open Validation to parse one.
          </p>
        ) : null}
      </section>
      <JobExecutionPanel yamlName={yamlName} pipelineNames={pipelineNames} onStatus={setStatus} />
    </div>
  );
}

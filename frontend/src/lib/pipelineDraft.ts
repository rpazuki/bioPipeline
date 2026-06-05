import yaml from "js-yaml";

import { REFERENCE_PARAMETER_NAMES } from "./pipelineGraph";

/**
 * A fidelity-preserving, editable model of a labUtils pipeline. Superset of the
 * lossy `PipelineSummary` returned by validation: it also carries input specs
 * (src/package/method + extras) and output file paths so the graph can be
 * serialized back to YAML.
 */
export interface InputDraft {
  name: string;
  src: string;
  package: string;
  method: string;
  /** Any other input-spec keys, e.g. value_column_name. */
  extras: Record<string, unknown>;
}

export interface ProcessDraft {
  name: string;
  package: string;
  method: string;
  parameters: Record<string, unknown>;
}

export interface OutputDraft {
  name: string;
  path: string;
}

export interface PipelineDraft {
  name: string;
  inputs: InputDraft[];
  processes: ProcessDraft[];
  outputs: OutputDraft[];
}

const INPUT_SPEC_KEYS = new Set(["src", "package", "method"]);

export function isPayloadRefKey(key: string): boolean {
  return REFERENCE_PARAMETER_NAMES.has(key) || key.endsWith("_df");
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Mirror of the backend `_coerce_input_spec`: accept a map or a list of one-item maps. */
function coerceInputSpec(raw: unknown): Record<string, unknown> | null {
  if (isPlainObject(raw)) return raw;
  if (Array.isArray(raw)) {
    const spec: Record<string, unknown> = {};
    for (const item of raw) {
      if (!isPlainObject(item)) return null;
      Object.assign(spec, item);
    }
    return spec;
  }
  return null;
}

function entriesOf(section: unknown): Array<[string, unknown]> {
  if (!Array.isArray(section)) return [];
  const entries: Array<[string, unknown]> = [];
  for (const item of section) {
    if (isPlainObject(item)) {
      const keys = Object.keys(item);
      if (keys.length === 1) entries.push([keys[0], item[keys[0]]]);
    }
  }
  return entries;
}

function parseInput(name: string, raw: unknown): InputDraft {
  const spec = coerceInputSpec(raw) ?? {};
  const extras: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(spec)) {
    if (!INPUT_SPEC_KEYS.has(key)) extras[key] = value;
  }
  return {
    name,
    src: spec.src == null ? "" : String(spec.src),
    package: spec.package == null ? "" : String(spec.package),
    method: spec.method == null ? "" : String(spec.method),
    extras,
  };
}

function parseProcess(name: string, raw: unknown): ProcessDraft {
  const spec = isPlainObject(raw) ? raw : {};
  const parameters = isPlainObject(spec.parameters) ? spec.parameters : {};
  return {
    name,
    package: spec.package == null ? "" : String(spec.package),
    method: spec.method == null ? "" : String(spec.method),
    parameters,
  };
}

/**
 * Parse labUtils YAML text into editable drafts. Returns an error string when the
 * text is not parseable / not the labUtils pipelines shape, leaving the caller to
 * keep the last good graph rather than wiping it.
 */
export function parseYamlToDrafts(text: string): { drafts: PipelineDraft[]; error?: string } {
  let data: unknown;
  try {
    data = yaml.load(text);
  } catch (error) {
    return { drafts: [], error: error instanceof Error ? error.message : String(error) };
  }
  if (!isPlainObject(data)) {
    return { drafts: [], error: "YAML content must be a mapping" };
  }
  const pipelines = data.pipelines;
  if (!Array.isArray(pipelines)) {
    return { drafts: [], error: "YAML must contain a 'pipelines' list" };
  }

  const drafts: PipelineDraft[] = [];
  for (const entry of pipelines) {
    if (!isPlainObject(entry)) continue;
    const keys = Object.keys(entry);
    if (keys.length !== 1) continue;
    const name = keys[0];
    const config = entry[name];
    if (!isPlainObject(config)) continue;
    drafts.push({
      name,
      inputs: entriesOf(config.Inputs).map(([n, raw]) => parseInput(n, raw)),
      processes: entriesOf(config.Processes).map(([n, raw]) => parseProcess(n, raw)),
      outputs: entriesOf(config.Outputs).map(([n, path]) => ({
        name: n,
        path: path == null ? "" : String(path),
      })),
    });
  }
  return { drafts };
}

/**
 * Order processes so each one follows the processes it depends on (via payload
 * reference parameters). Kahn's algorithm; falls back to original order on a cycle.
 */
function topoSortProcesses(processes: ProcessDraft[]): ProcessDraft[] {
  const names = new Set(processes.map((process) => process.name));
  const indegree = new Map<string, number>();
  const dependents = new Map<string, string[]>();
  for (const process of processes) {
    indegree.set(process.name, 0);
    dependents.set(process.name, []);
  }

  for (const process of processes) {
    const deps = new Set<string>();
    for (const [key, value] of Object.entries(process.parameters)) {
      if (typeof value === "string" && isPayloadRefKey(key) && names.has(value) && value !== process.name) {
        deps.add(value);
      }
    }
    for (const dep of deps) {
      dependents.get(dep)!.push(process.name);
      indegree.set(process.name, (indegree.get(process.name) ?? 0) + 1);
    }
  }

  const byName = new Map(processes.map((process) => [process.name, process]));
  // Seed the queue in original order to keep the layout stable.
  const queue = processes.filter((process) => (indegree.get(process.name) ?? 0) === 0).map((p) => p.name);
  const ordered: ProcessDraft[] = [];
  while (queue.length > 0) {
    const name = queue.shift()!;
    ordered.push(byName.get(name)!);
    for (const next of dependents.get(name) ?? []) {
      const remaining = (indegree.get(next) ?? 0) - 1;
      indegree.set(next, remaining);
      if (remaining === 0) queue.push(next);
    }
  }

  return ordered.length === processes.length ? ordered : processes;
}

function emitInputSpec(input: InputDraft): Record<string, unknown> {
  return { src: input.src, package: input.package, method: input.method, ...input.extras };
}

/** Build the exact labUtils nested shape and dump it to YAML text. */
export function emitDraftsToYaml(drafts: PipelineDraft[]): string {
  const doc = {
    pipelines: drafts.map((draft) => ({
      [draft.name]: {
        Inputs: draft.inputs.map((input) => ({ [input.name]: emitInputSpec(input) })),
        Processes: topoSortProcesses(draft.processes).map((process) => ({
          [process.name]: {
            package: process.package,
            method: process.method,
            parameters: process.parameters,
          },
        })),
        Outputs: draft.outputs.map((output) => ({ [output.name]: output.path })),
      },
    })),
  };

  return yaml.dump(doc, { indent: 2, lineWidth: -1, sortKeys: false, noRefs: true });
}

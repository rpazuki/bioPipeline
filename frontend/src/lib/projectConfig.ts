import fs from "node:fs";
import path from "node:path";

import yaml from "js-yaml";

type GenericMap = Record<string, unknown>;

type FrontendConfig = {
  api_url: string;
  api_prefix: string;
};

type AppConfigDocument = {
  defaults?: {
    environment?: string;
  };
  frontend?: {
    shared?: GenericMap;
    [key: string]: unknown;
  };
};

const DEFAULT_CONFIG_PATH = path.resolve(process.cwd(), "..", "configs", "app_config.yaml");

function isRecord(value: unknown): value is GenericMap {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function deepMerge(base: GenericMap, override: GenericMap): GenericMap {
  const merged: GenericMap = { ...base };
  for (const [key, value] of Object.entries(override)) {
    const existing = merged[key];
    if (isRecord(existing) && isRecord(value)) {
      merged[key] = deepMerge(existing, value);
      continue;
    }
    merged[key] = value;
  }
  return merged;
}

function normalizePrefix(prefix: string): string {
  if (!prefix.startsWith("/")) {
    return `/${prefix}`;
  }
  return prefix;
}

export function loadProjectConfigDocument(configPath?: string): AppConfigDocument {
  const effectivePath = path.resolve(configPath ?? process.env.APP_CONFIG_PATH ?? DEFAULT_CONFIG_PATH);
  if (!fs.existsSync(effectivePath)) {
    return {};
  }
  const parsed = yaml.load(fs.readFileSync(effectivePath, "utf-8"));
  return isRecord(parsed) ? (parsed as AppConfigDocument) : {};
}

export function resolveEnvironment(doc: AppConfigDocument, envName?: string): string {
  if (envName) {
    return envName.toLowerCase();
  }
  if (process.env.APP_ENV) {
    return process.env.APP_ENV.toLowerCase();
  }
  if (doc.defaults?.environment) {
    return doc.defaults.environment.toLowerCase();
  }
  if (process.env.NODE_ENV) {
    return process.env.NODE_ENV.toLowerCase();
  }
  return "development";
}

export function loadFrontendConfig(options?: {
  configPath?: string;
  envName?: string;
  env?: NodeJS.ProcessEnv;
}): FrontendConfig {
  const env = options?.env ?? process.env;
  const doc = loadProjectConfigDocument(options?.configPath);
  const frontend = isRecord(doc.frontend) ? doc.frontend : {};
  const shared = isRecord(frontend.shared) ? frontend.shared : {};

  const activeEnv = resolveEnvironment(doc, options?.envName);
  const envConfig = isRecord(frontend[activeEnv]) ? (frontend[activeEnv] as GenericMap) : {};
  const merged = deepMerge(shared, envConfig);

  const api_url = String(env.NEXT_PUBLIC_API_URL ?? merged.api_url ?? "http://localhost:8005");
  const api_prefix = normalizePrefix(String(env.NEXT_PUBLIC_API_PREFIX ?? merged.api_prefix ?? "/api/v1"));

  return { api_url, api_prefix };
}

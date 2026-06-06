import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { loadFrontendConfig, resolveEnvironment } from "./projectConfig";

const SAMPLE_CONFIG = `
defaults:
  environment: development
frontend:
  shared:
    api_prefix: /api/v1
  development:
    api_url: http://localhost:8005
  production:
    api_url: https://api.example.com
`;

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("projectConfig", () => {
  it("merges shared frontend config with selected environment", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "frontend-config-"));
    const configPath = path.join(dir, "app_config.yaml");
    fs.writeFileSync(configPath, SAMPLE_CONFIG, "utf-8");

    const config = loadFrontendConfig({ configPath, envName: "production" });

    expect(config.api_url).toBe("https://api.example.com");
    expect(config.api_prefix).toBe("/api/v1");
  });

  it("prioritizes explicit env variables", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "frontend-config-"));
    const configPath = path.join(dir, "app_config.yaml");
    fs.writeFileSync(configPath, SAMPLE_CONFIG, "utf-8");

    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://env-only.example");
    vi.stubEnv("NEXT_PUBLIC_API_PREFIX", "v2");

    const config = loadFrontendConfig({ configPath, envName: "production" });

    expect(config.api_url).toBe("http://env-only.example");
    expect(config.api_prefix).toBe("/v2");
  });

  it("falls back to defaults.environment when APP_ENV is unset", () => {
    const doc = {
      defaults: { environment: "production" },
    };

    expect(resolveEnvironment(doc)).toBe("production");
  });
});

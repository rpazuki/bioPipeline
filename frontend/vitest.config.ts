import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
  },
  resolve: {
    alias: {
      // Mirror the tsconfig "@/*" -> "./src/*" path alias so runtime imports
      // (e.g. `@/lib/api`) resolve under vitest, not just type-only imports.
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});

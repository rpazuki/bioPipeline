// Flat ESLint config (ESLint 9 + Next.js 16). Next 16 removed the `next lint`
// subcommand, so linting runs through the ESLint CLI against this file. The
// `eslint-config-next` package ships a native flat-config array we spread in.
import next from "eslint-config-next";

/** @type {import("eslint").Linter.Config[]} */
const config = [
  ...next,
  {
    ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts"],
  },
  {
    // eslint-config-next 16 turns on React Compiler's stricter hook rules as errors.
    // `set-state-in-effect` flags this codebase's pre-existing mount-time refresh
    // pattern (an async refresh() that setStates only after awaiting). Keep it visible
    // as a warning rather than failing the build; refactoring those effects off the
    // pattern is separate tech debt, not part of the typed-definitions work.
    rules: {
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default config;

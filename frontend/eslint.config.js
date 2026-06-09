import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "*.config.js", "*.config.ts"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      // Stable hooks rules (rules-of-hooks + exhaustive-deps).
      ...reactHooks.configs.recommended.rules,
      // React-Compiler-era rules. Now enforced: data fetching moved to
      // TanStack Query and template/resume seeding uses keyed components, so
      // no effect sets state synchronously; the one defensive fallback
      // assignment in api.ts was restructured. See hooks/ and components/.
      "react-hooks/set-state-in-effect": "error",
      "no-useless-assignment": "error",
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
);

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
      // Stable hooks rules (rules-of-hooks + exhaustive-deps). We deliberately
      // avoid react-hooks 7's "recommended-latest", whose new React-Compiler
      // rules (e.g. set-state-in-effect) flag working effects and would force
      // refactors out of scope for lint adoption.
      ...reactHooks.configs.recommended.rules,
      // Opinionated React-Compiler-era rules that flag working, intentional
      // patterns in this codebase (loading-state effects, defensive fallback
      // assignment). Disabled so lint catches real bugs without forcing
      // refactors. Revisit if the app adopts the React Compiler.
      "react-hooks/set-state-in-effect": "off",
      "no-useless-assignment": "off",
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
);

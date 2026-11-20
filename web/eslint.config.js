import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ["**/*.{ts,tsx,js}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "no-var": "error",
      "prefer-const": "error",
      "no-console": "error",
      "no-nested-ternary": "error",
      "prefer-arrow-callback": "error",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/explicit-module-boundary-types": "error",
      "max-lines-per-function": ["error", { max: 50, skipBlankLines: true, skipComments: true }],
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
  {
    // A describe() callback wraps a whole suite, so the per-function limit would
    // cap the size of a test file rather than the size of a unit of logic.
    files: ["**/*.test.{ts,tsx}"],
    rules: { "max-lines-per-function": "off" },
  }
);

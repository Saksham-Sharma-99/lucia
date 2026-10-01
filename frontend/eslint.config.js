import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src/api/generated", "src/routeTree.gen.ts"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended, prettier],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
  {
    // Route files export a Route object, and shadcn ui files export variants, next to components.
    files: ["src/routes/**/*.tsx", "src/components/ui/**/*.tsx"],
    rules: { "react-refresh/only-export-components": "off" },
  },
);

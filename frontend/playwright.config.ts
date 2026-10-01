import { defineConfig } from "@playwright/test";

// Runs against a live stack (`make dev` + `make seed`); set E2E_PASSWORD to the seed password.
// The teardown deletes the run's data from the dev database afterwards.
export default defineConfig({
  testDir: "e2e",
  globalTeardown: "./e2e/teardown.ts",
  timeout: 60_000,
  fullyParallel: false,
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173", trace: "retain-on-failure" },
});

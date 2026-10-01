import { defineConfig } from "@hey-api/openapi-ts";

// Generates a typed client from the running backend's schema (make gen-client).
export default defineConfig({
  input: process.env.OPENAPI_URL ?? "http://localhost:8000/openapi.json",
  output: { path: "src/api/generated" },
  plugins: ["@hey-api/client-fetch", "@tanstack/react-query"],
});

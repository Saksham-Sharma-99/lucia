import { defineConfig } from "@hey-api/openapi-ts";

// Generates a typed client from the running backend's schema (make gen-client).
export default defineConfig({
  input: process.env.OPENAPI_URL ?? "http://localhost:8000/openapi.json",
  output: { path: "src/api/generated" },
  // baseUrl: false keeps the generation URL out of the client; main.tsx sets it at runtime.
  plugins: [{ name: "@hey-api/client-fetch", baseUrl: false }, "@tanstack/react-query"],
});

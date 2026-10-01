import { execFileSync } from "node:child_process";
import path from "node:path";

/** After every run, hard-delete what the smoke flows created (agents @e2e-*, firms e2e-firm-*). */
export default function teardown() {
  execFileSync("uv", ["run", "python", "-m", "lucia.seeds.cleanup_e2e"], {
    cwd: path.resolve(import.meta.dirname, "../../backend"),
    stdio: "inherit",
  });
}

import { execSync } from "node:child_process";
import path from "node:path";

export default function globalSetup() {
  const root = path.resolve(__dirname, "..", "..", "..");
  // Isolation from another checkout: set CL_COMPOSE_PROJECT / CL_COMPOSE_EXTRA_FILE to target this
  // worktree's own project and override file (see infra/dev-isolation/docker-compose.authoring.yml).
  const args = ["compose"];
  if (process.env.CL_COMPOSE_PROJECT) args.push("-p", process.env.CL_COMPOSE_PROJECT);
  args.push("-f", "infra/docker-compose.yml");
  if (process.env.CL_COMPOSE_EXTRA_FILE) args.push("-f", process.env.CL_COMPOSE_EXTRA_FILE);
  args.push("exec", "-T", "api", "python", "-m", "app.demo", "reset");
  const out = execSync(`docker ${args.join(" ")}`,
    { cwd: root, encoding: "utf-8", env: { ...process.env, MSYS_NO_PATHCONV: "1" } });
  if (!out.includes("RESULT: READY")) throw new Error(`demo reset failed:\n${out}`);
}

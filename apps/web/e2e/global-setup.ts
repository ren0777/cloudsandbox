import { execSync } from "node:child_process";
import path from "node:path";

export default function globalSetup() {
  const root = path.resolve(__dirname, "..", "..", "..");
  const out = execSync("docker compose -f infra/docker-compose.yml exec -T api python -m app.demo reset",
    { cwd: root, encoding: "utf-8", env: { ...process.env, MSYS_NO_PATHCONV: "1" } });
  if (!out.includes("RESULT: READY")) throw new Error(`demo reset failed:\n${out}`);
}

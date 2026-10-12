import { defineConfig, devices } from "@playwright/test";

// Production smoke test (docs/DEPLOYMENT.md §11): runs against a DEPLOYED server, never resets anything.
//   CLOUDLABS_URL=https://labs.college.edu CLOUDLABS_ADMIN_EMAIL=… CLOUDLABS_ADMIN_PASSWORD=… \
//     npx playwright test -c playwright.prod.config.ts
// CLOUDLABS_INSECURE_TLS=1 accepts a self-signed certificate (local rehearsal only).
if (!process.env.CLOUDLABS_URL) throw new Error("set CLOUDLABS_URL to the deployed site, e.g. https://labs.college.edu");

export default defineConfig({
  testDir: "./e2e-prod",
  timeout: 600_000,
  expect: { timeout: 30_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.CLOUDLABS_URL,
    ignoreHTTPSErrors: process.env.CLOUDLABS_INSECURE_TLS === "1",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});

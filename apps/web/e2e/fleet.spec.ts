import { expect, test } from "@playwright/test";

// Phase 7: the admin sees the runner fleet (health, engines, memory) and can drain and resume a runner.
// Needs the second runner (docker compose --profile multi up -d runner2), registered as runner-local-2 by default (CLOUDLABS_RUNNER2_ID overrides).
test("admin drains and resumes a runner", async ({ page }) => {
  const R2 = process.env.CLOUDLABS_RUNNER2_ID ?? "runner-local-2";
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-admin@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/admin\/status/);
  const rows = page.getByTestId("runner-row");
  await expect(rows.first()).toBeVisible();
  const second = rows.filter({ hasText: R2 });
  test.skip((await second.count()) === 0, `${R2} is not registered on this stack`);
  await expect(second).toContainText("Healthy");
  await expect(second).toContainText("floci");
  await expect(second).toContainText("GiB free");

  page.once("dialog", (d) => void d.accept("e2e maintenance window"));
  await second.getByTestId("drain-runner").click();
  await expect(second.getByTestId("runner-draining")).toContainText("safe to stop");
  await page.screenshot({ path: "../../docs/screenshots/21-runner-fleet.png", fullPage: true });
  await second.getByRole("button", { name: "Resume" }).click();
  await expect(second.getByTestId("runner-draining")).toHaveCount(0);

  await page.goto("/admin/audit");
  await expect(page.getByTestId("audit-row").filter({ hasText: `Drained runner ${R2}` }).first()).toContainText("e2e maintenance window");
});

import { expect, type Page, test } from "@playwright/test";

// Phase 6: the live architecture diagram follows the sandbox (a CLI change appears without reloading), and the
// result page shows what was built at submission.

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 60_000 });
}

test("architecture diagram updates as the student builds", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-student2@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("lab-card").filter({ hasText: "Mission 2" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  await page.getByTestId("tab-diagram").click();
  await expect(page.getByTestId("arch-empty")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, "aws dynamodb create-table --table-name cafe-demo02-orders --attribute-definitions AttributeName=orderId,AttributeType=S --key-schema AttributeName=orderId,KeyType=HASH --billing-mode PAY_PER_REQUEST >/dev/null && echo TB_$((40+2))", "TB_42");

  await page.getByTestId("tab-diagram").click();
  const node = page.locator('[data-node="dynamodb:cafe-demo02-orders"]');
  await expect(node).toBeVisible({ timeout: 30_000 });  // appears on the next poll, no reload
  await expect(node).toContainText("on-demand");
  await page.screenshot({ path: "../../docs/screenshots/17-architecture.png" });

  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 120_000 });
  await expect(page.getByTestId("result-architecture").locator('[data-node="dynamodb:cafe-demo02-orders"]')).toBeVisible();
});

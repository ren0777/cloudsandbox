import { expect, type Page, test } from "@playwright/test";

// Mission 16 (audit proxy, default engine): bucket in the console → ledger uploaded from the CLI BEFORE versioning
// → versioning enabled in the console. Every resource check passes, but the audit log shows the wrong order:
// 70, with the lab's explanation. Uploading again from the CLI (the real fix in AWS) → 100.

const BUCKET = "cafe-demo03-ledger";

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 120_000 });
}

test("the audit log catches an upload made before versioning, and the student fixes it", async ({ page }) => {
  test.setTimeout(600_000);
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-student3@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("lab-card").filter({ hasText: "Mission 16: CloudCafé's audit trail" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  // 1) Console: create the bucket
  await page.getByTestId("open-create-bucket").click();
  await page.getByTestId("new-bucket-name").fill(BUCKET);
  await page.getByTestId("create-bucket").click();
  await expect(page.getByText(`Successfully created bucket "${BUCKET}".`)).toBeVisible({ timeout: 30_000 });

  // 2) CLI: upload the ledger too early
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, `echo date,total > ledger.csv && aws s3 cp ledger.csv s3://${BUCKET}/ledger.csv && echo UP_$((40+2))`, "UP_42");

  // 3) Console: enable versioning afterwards
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("button", { name: BUCKET }).click();
  await page.getByRole("tab", { name: "Properties" }).click();
  await page.getByTestId("edit-versioning").click();
  await page.getByTestId("versioning-enable").check();
  await page.getByTestId("save-versioning").click();
  await expect(page.getByTestId("versioning-status")).toHaveText("Enabled", { timeout: 30_000 });

  // 4) Everything exists, but the order was wrong: 70, and the lab says why
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("70.00 / 100", { timeout: 120_000 });
  await expect(page.getByTestId("task-upload-ledger")).toHaveClass(/done/);
  await expect(page.getByTestId("task-upload-from-cli")).toHaveClass(/done/);
  await expect(page.getByTestId("task-versioning-first")).toHaveClass(/todo/);
  await expect(page.getByTestId("task-versioning-first")).toContainText("its version ID is null");
  await page.getByTestId("task-upload-from-cli").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../../docs/screenshots/39-audit-order.png" });

  // 5) The fix: upload again now that versioning is on
  await page.getByTestId("tab-terminal").click();
  await termRun(page, `aws s3 cp ledger.csv s3://${BUCKET}/ledger.csv && echo AGAIN_$((40+2))`, "AGAIN_42");
  await page.getByRole("tab", { name: "Console" }).click();
  await page.waitForTimeout(10_500); // progress checks are rate-limited to 1 per 10 s
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100", { timeout: 120_000 });
  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 180_000 });
  await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
});

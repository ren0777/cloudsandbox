import { execSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

// PLAN "Slice 1 is done when" #4 — the full journey through the real UI on the real runtime:
// GUI creates → CLI proves → CLI modifies → GUI proves → deliberate partial score → fix → 100 →
// instructor sees result + per-check evidence → sandbox cleaned up.

const PASSWORD = "cloudlabs-demo";
// An isolated Compose project runs under its own runner id (infra/docker-compose.*.yml), so the admin's
// runner row must not be hardcoded — the same rule fleet.spec.ts already follows for runner2.
const RUNNER_ID = process.env.CLOUDLABS_RUNNER_ID ?? "runner-local-1";
const BUCKET = "cafe-demo01-site";
let sessionId = "";
const shot = (page: Page, name: string) => page.screenshot({ path: `../../docs/screenshots/${name}.png` });

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 5 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 60_000 });
}

function sandboxContainers(id: string): string {
  return execSync(`docker ps -a -q --filter label=cloudlabs.session=${id}`, { encoding: "utf-8" }).trim()
    + execSync(`docker network ls -q --filter label=cloudlabs.session=${id}`, { encoding: "utf-8" }).trim();
}

test.describe.serial("student journey (GUI + CLI) and instructor evidence", () => {
  test("student completes the S3 lab with console and terminal", async ({ page }) => {
    await signIn(page, "demo-student1@cloudlabs.demo");
    await expect(page.getByRole("heading", { name: "My labs" })).toBeVisible();
    await expect(page.getByTestId("lab-card").first()).toBeVisible();
    await shot(page, "01-my-labs");
    await page.getByTestId("lab-card").filter({ hasText: "Mission 1: CloudCafé goes online" }).click();
    await expect(page.getByRole("heading", { name: /CloudCafé goes online/ })).toBeVisible();
    await shot(page, "02-lab-brief");
    await page.getByTestId("start-lab").click();

    await page.waitForURL(/\/play\?session=/);
    sessionId = new URL(page.url()).searchParams.get("session")!;
    await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });
    expect(sandboxContainers(sessionId)).not.toBe("");

    // Progressive hints: the first hint says where to look, not what to type.
    await page.getByTestId("hint-enable-versioning").click();
    await expect(page.getByTestId("task-enable-versioning")).toContainText("look under Properties");
    await expect(page.getByTestId("task-enable-versioning")).not.toContainText("put-bucket-versioning");

    // 1) GUI: S3 → Buckets → Create bucket (AWS-style form, defaults kept).
    await page.getByTestId("open-create-bucket").click();
    await expect(page.getByRole("heading", { name: "Block Public Access settings for this bucket" })).toBeVisible();
    await expect(page.getByText("Not available in Stackora simulator").first()).toBeVisible();
    await page.getByTestId("new-bucket-name").fill(BUCKET);
    await page.getByTestId("create-bucket").click();
    await expect(page.getByText(`Successfully created bucket "${BUCKET}".`)).toBeVisible();
    await expect(page.getByRole("button", { name: BUCKET })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Bucket and objects not public" })).toBeVisible();
    await shot(page, "02b-console-buckets");

    // 2) CLI proves it, then changes state.
    await page.getByTestId("tab-terminal").click();
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".xterm-rows")).toContainText("Stackora AWS CLI environment");
    await termRun(page, "aws s3 ls | sed s/^/LS:/", `LS:`);
    await expect(page.locator(".xterm-rows")).toContainText(new RegExp(`LS:.*${BUCKET}`));
    await termRun(page, `aws s3api put-bucket-versioning --bucket ${BUCKET} --versioning-configuration Status=Enabled && echo VERSIONING_$((40+2))`, "VERSIONING_42");
    await shot(page, "03-terminal");
    await termRun(page, `echo '<h1>CloudCafe</h1>' > index.html && aws s3 cp index.html s3://${BUCKET}/ && echo UPLOADED_$((40+2))`, "UPLOADED_42");

    // 3) GUI proves the CLI changes.
    await page.getByRole("tab", { name: "Console" }).click();
    await page.getByRole("button", { name: "Refresh" }).click();
    await page.getByRole("button", { name: BUCKET }).click();
    await expect(page.getByRole("cell", { name: "index.html", exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Properties" }).click();
    await expect(page.getByTestId("versioning-status")).toHaveText("Enabled");

    // 4) Deliberately incomplete: the tag task is missing → 75.
    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("75.00 / 100");
    await expect(page.getByTestId("task-tag-bucket")).toContainText("should have tag project=cloudcafe");
    await expect(page.getByTestId("task-create-bucket")).toHaveClass(/done/);
    await shot(page, "04-progress-75");

    // 5) Fix it in the GUI (Properties → Tags → Edit → Save changes), re-check → 100.
    await page.getByTestId("edit-tags").click();
    await page.getByTestId("add-tag").click();
    await page.getByLabel("Tag key").fill("project");
    await page.getByLabel("Tag value").fill("cloudcafe");
    await page.getByTestId("save-tags").click();
    await expect(page.getByText("Successfully edited tags.")).toBeVisible();
    await shot(page, "04b-console-properties");
    await page.waitForTimeout(10_500); // progress checks are rate-limited to 1 per 10 s
    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");

    // 6) Submit → stored result.
    await page.getByTestId("submit-lab").click();
    await page.getByTestId("confirm-action").click();
    await page.waitForURL(/\/results\//, { timeout: 120_000 });
    await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
    await expect(page.getByText("Every task passed")).toBeVisible();
    await shot(page, "05-result-100");

    // 7) Cleanup: containers and network are gone.
    await expect.poll(() => sandboxContainers(sessionId), { timeout: 90_000, intervals: [1000] }).toBe("");
  });

  test("instructor sees the stored result and per-check evidence", async ({ page }) => {
    await signIn(page, "demo-instructor@cloudlabs.demo");
    await expect(page.getByRole("heading", { name: "Courses" })).toBeVisible();
    await page.getByTestId("assignment-link").filter({ hasText: "Mission 1: CloudCafé goes online" }).click();
    const row = page.getByTestId("result-row").filter({ hasText: "Sam Student" });
    await expect(row).toContainText("100.00");
    await row.getByRole("link", { name: /#1: 100.00/ }).click();
    await expect(page.getByTestId("instructor-score")).toContainText("100.00");
    await expect(page.getByTestId("evidence-check")).toHaveCount(5);
    await expect(page.getByTestId("evidence-check").first()).toContainText("s3.bucket_exists");
    await expect(page.getByText("sha256", { exact: false }).first()).toBeVisible();
    await page.screenshot({ path: "../../docs/screenshots/06-instructor-evidence.png", fullPage: true });
  });

  test("admin sees runtime status", async ({ page }) => {
    await signIn(page, "demo-admin@cloudlabs.demo");
    await expect(page.getByRole("heading", { name: "Runtime status" })).toBeVisible();
    // anchored: "runner-m45" must not also match "runner-m45-2" when a second runner is registered
    await expect(page.getByRole("cell", { name: new RegExp(`^${RUNNER_ID}(\\s|$)`) })).toBeVisible();
    await expect(page.getByText("Healthy").first()).toBeVisible();
    await shot(page, "07-runtime-status");
  });
});

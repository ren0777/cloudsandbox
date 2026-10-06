import { execSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

// IAM journey: GUI user group + JSON customer managed policy attached to the group, CLI creates the user
// and adds it to the group, the Stackora policy simulator proves least privilege, submit → 100.

const PASSWORD = "cloudlabs-demo";
const ID = "demo03";
const GROUP = `baristas-${ID}`, USER = `barista-${ID}`, POLICY = `menu-read-${ID}`, BUCKET = `cafe-${ID}-site`;

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 3 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 60_000 });
}

test("student completes the IAM least-privilege lab", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-student3@cloudlabs.demo");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("lab-card").filter({ hasText: "Mission 3" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  const sessionId = new URL(page.url()).searchParams.get("session")!;
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });
  await expect(page.getByTestId("iam-users")).toBeVisible(); // console opens on IAM

  // 1) GUI: create the user group
  await page.getByTestId("iam-groups").click();
  await page.getByTestId("open-create-group").click();
  await page.getByTestId("new-group-name").fill(GROUP);
  await page.getByTestId("create-group").click();
  await expect(page.getByText(`User group ${GROUP} created.`)).toBeVisible();

  // 2) GUI: customer managed policy with the JSON editor, then attach it to the group
  await page.getByTestId("iam-policies").click();
  await page.getByTestId("open-create-policy").click();
  await page.getByTestId("policy-json").fill(JSON.stringify({ Version: "2012-10-17", Statement: [
    { Effect: "Allow", Action: "s3:GetObject", Resource: `arn:aws:s3:::${BUCKET}/*` }] }, null, 2));
  await page.getByTestId("wizard-next").click();
  await page.getByTestId("new-policy-name").fill(POLICY);
  await page.getByTestId("create-policy").click();
  await expect(page.getByText(`Policy ${POLICY} created.`)).toBeVisible();
  await page.getByTestId("iam-groups").click();
  await page.getByRole("button", { name: GROUP }).click();
  await page.getByTestId("add-permissions").click();
  await page.getByTestId("policy-filter").fill(POLICY);
  await page.getByLabel(`Select ${POLICY}`).check();
  await page.getByTestId("attach-policies").click();
  await expect(page.getByText("Policies attached.")).toBeVisible();

  // 3) CLI: create the user and add it to the group (standard AWS CLI syntax)
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, `aws iam create-user --user-name ${USER} >/dev/null && aws iam add-user-to-group --group-name ${GROUP} --user-name ${USER} && echo IAM_$((40+2))`, "IAM_42");

  // 4) GUI: the user shows its group; the policy simulator proves least privilege
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByTestId("iam-users").click();
  await expect(page.getByRole("cell", { name: GROUP })).toBeVisible();
  await page.getByTestId("iam-simulator").click();
  await page.getByTestId("sim-principal").selectOption(`user:${USER}`);
  await page.getByTestId("sim-actions").fill("s3:GetObject, s3:DeleteObject");
  await page.getByTestId("sim-resource").fill(`arn:aws:s3:::${BUCKET}/menu.html`);
  await page.getByTestId("run-simulation").click();
  await expect(page.getByTestId("sim-result").nth(0)).toContainText("Allowed");
  await expect(page.getByTestId("sim-result").nth(1)).toContainText("Denied");
  await expect(page.getByText("Simulated by Stackora")).toBeVisible();
  await page.screenshot({ path: "../../docs/screenshots/10-iam-simulator.png" });

  // 5) Progress → 100, submit, cleanup
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 120_000 });
  await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  await expect.poll(() => execSync(`docker ps -a -q --filter label=cloudlabs.session=${sessionId}`, { encoding: "utf-8" }).trim(),
    { timeout: 90_000, intervals: [1000] }).toBe("");
});

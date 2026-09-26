import { expect, type Page, test } from "@playwright/test";

// Phase 6 journey: instructor enables an anonymous leaderboard → student opens the break-fix mission (starts
// broken: the diagram flags the admin group; cost meter is labelled simulated) → repairs it in the CLI → full
// marks, badges on the result page → XP on the progress card and a rank on the leaderboard.

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 90_000 });
}

test("break-fix lab, simulated cost, badges and leaderboard", async ({ page, browser }) => {
  test.setTimeout(360_000);
  // Instructor: anonymous leaderboard for the demo course
  const ictx = await browser.newContext();
  const inst = await ictx.newPage();
  await signIn(inst, "demo-instructor@cloudlabs.demo");
  await inst.getByTestId("course-card").filter({ hasText: "CLOUD-DEMO" }).getByTestId("course-link").click();
  await inst.getByTestId("leaderboard-mode").selectOption("anonymous");
  await expect(inst.getByTestId("leaderboard-mode")).toHaveValue("anonymous");
  await ictx.close();

  // Student: the break-fix mission starts broken
  await signIn(page, "demo-student1@cloudlabs.demo");
  const card = page.getByTestId("lab-card").filter({ hasText: "Mission 6" });
  await expect(card.getByTestId("breakfix-tag")).toBeVisible();
  await card.click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 180_000 });
  await expect(page.getByTestId("breakfix-banner")).toBeVisible();

  await page.getByTestId("tab-diagram").click();
  const group = page.locator('[data-node="iam:group:baristas-demo01"]');
  await expect(group).toBeVisible({ timeout: 30_000 });
  await expect(group.locator(".arch-flag")).toBeVisible();   // AdministratorAccess attached
  await expect(page.getByTestId("cost-meter")).toContainText("Simulated · educational");
  await expect(page.getByTestId("cost-meter")).toContainText("not AWS billing");
  await page.screenshot({ path: "../../docs/screenshots/18-breakfix-broken.png" });

  // Repair from the CLI
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, "aws iam detach-group-policy --group-name baristas-demo01 --policy-arn arn:aws:iam::aws:policy/AdministratorAccess && echo D_$((40+2))", "D_42");
  await termRun(page, "ARN=$(aws iam list-policies --scope Local --query \"Policies[?PolicyName=='orders-rw-demo01'].Arn\" --output text) && aws iam attach-group-policy --group-name baristas-demo01 --policy-arn $ARN && echo A_$((40+2))", "A_42");
  await termRun(page, "aws iam remove-user-from-group --group-name baristas-demo01 --user-name intern-demo01 && aws iam delete-user-policy --user-name intern-demo01 --policy-name temp-everything && aws iam delete-user --user-name intern-demo01 && echo O_$((40+2))", "O_42");

  // The diagram follows: no admin flag, no intern
  await page.getByTestId("tab-diagram").click();
  await expect(page.locator('[data-node="iam:user:intern-demo01"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(group.locator(".arch-flag")).toHaveCount(0);

  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100", { timeout: 60_000 });
  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 120_000 });
  const badges = page.getByTestId("badges-earned");
  await expect(badges).toContainText("Incident responder");
  await expect(badges).toContainText("Right first time");
  await expect(page.getByTestId("result-architecture").getByTestId("cost-meter")).toBeVisible();
  await page.screenshot({ path: "../../docs/screenshots/19-badges.png", fullPage: true });

  // Progress card and leaderboard
  await page.goto("/labs");
  await expect(page.getByTestId("xp-total")).not.toHaveText("0 XP");
  await expect(page.getByTestId("badge-earned").filter({ hasText: "Incident responder" })).toBeVisible();
  await page.getByTestId("leaderboard-link").first().click();
  const me = page.getByTestId("board-row").filter({ hasText: "You" });
  await expect(me).toBeVisible();
  await expect(page.getByTestId("board-row").filter({ hasText: "Sam Student" })).toHaveCount(0);  // anonymous
  await page.screenshot({ path: "../../docs/screenshots/20-leaderboard.png" });
});

import { expect, type Page, test } from "@playwright/test";

// Phase 5 journey: instructor creates a course → roster CSV preview shows row errors → fixed file imports →
// temporary passwords shown once → instructor assigns a lab → the new student signs in, must choose a
// password, and sees the lab.

const RUN = Date.now().toString(36).slice(-5);
const CODE = `E2E-${RUN}`.toUpperCase();
const NEW = `asha.${RUN}@cloudlabs.demo`;

async function signIn(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("instructor imports a roster and a new student signs in", async ({ page, browser }) => {
  await signIn(page, "demo-instructor@cloudlabs.demo", "cloudlabs-demo");
  await page.getByTestId("new-course").click();
  await page.getByTestId("course-code").fill(CODE);
  await page.getByTestId("course-title").fill("Cloud Computing E2E");
  await page.getByTestId("course-save").click();
  await page.getByTestId("course-card").filter({ hasText: CODE }).getByTestId("course-link").click();
  await expect(page.getByRole("heading", { name: new RegExp(CODE) })).toBeVisible();

  // 1) Preview with problems: an invalid email and a duplicate
  const bad = `email,name\n${NEW},Asha Patel\nnot-an-email,Broken Row\n${NEW},Asha Again\ndemo-student2@cloudlabs.demo,Priya\n`;
  await page.getByTestId("roster-text").fill(bad);
  await page.getByTestId("roster-preview").click();
  await expect(page.getByTestId("roster-error-count")).toHaveText("2 with errors");
  await expect(page.getByTestId("roster-issue").filter({ hasText: "duplicate of row 2" })).toBeVisible();
  await expect(page.getByTestId("roster-issue").filter({ hasText: "invalid email" })).toBeVisible();
  await expect(page.getByTestId("roster-import-commit")).toHaveCount(0);

  // 2) Fixed file → import 2 (one new account, one existing student)
  await page.getByTestId("roster-text").fill(`email,name\n${NEW},Asha Patel\ndemo-student2@cloudlabs.demo,Priya\n`);
  await page.getByTestId("roster-preview").click();
  await expect(page.getByTestId("roster-error-count")).toHaveText("0 with errors");
  await page.getByTestId("roster-import-commit").click();
  await expect(page.getByTestId("roster-result")).toContainText("1 new account created, 1 existing student enrolled");
  await expect(page.getByTestId("roster-credentials")).toContainText("shown only now");
  const download = page.waitForEvent("download");
  await page.getByTestId("download-credentials").click();
  const file = await (await download).path();
  const csv = (await import("node:fs")).readFileSync(file!, "utf-8");
  const tmp = csv.split(/\r?\n/).find((l) => l.includes(NEW))!.split(",")[2].replace(/"/g, "");
  expect(tmp).toMatch(/^[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}$/);
  await expect(page.getByTestId("roster-row")).toHaveCount(2);
  await expect(page.getByTestId("roster-row").filter({ hasText: NEW })).toContainText("Awaiting first sign-in");
  await page.screenshot({ path: "../../docs/screenshots/13-roster-import.png", fullPage: true });

  // 3) Assign a lab
  await page.getByTestId("new-assignment").click();
  await page.getByTestId("asg-lab").selectOption({ label: "Mission 1: CloudCafé goes online · v1.2.0" }).catch(async () => {
    await page.getByTestId("asg-lab").selectOption({ index: 0 });
  });
  await page.getByTestId("asg-title").fill("Week 1: S3 website");
  await page.getByTestId("asg-save").click();
  await expect(page.getByTestId("assignment-link").filter({ hasText: "Week 1: S3 website" })).toBeVisible();

  // 4) The new student must change the temporary password, then sees the lab
  const ctx = await browser.newContext();
  const stu = await ctx.newPage();
  await signIn(stu, NEW, tmp);
  await stu.waitForURL(/\/account\/password/);
  await stu.getByTestId("current-password").fill(tmp);
  await stu.getByTestId("new-password").fill("my-own-password-1");
  await stu.getByTestId("repeat-password").fill("my-own-password-1");
  await stu.getByTestId("save-password").click();
  await stu.waitForURL(/\/labs/);
  await expect(stu.getByTestId("lab-card").filter({ hasText: CODE })).toBeVisible();
  await ctx.close();
});

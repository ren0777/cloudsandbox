import { expect, type Page, test } from "@playwright/test";

// Phase 5 operations: a student works on Mission 1 → the instructor watches live progress, extends the lab,
// ends it with grading → gradebook shows the score and drills into the evidence → CSV export → the admin sees
// every action in the audit log, the users list and runtime engine health.

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
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 60_000 });
}

test("instructor monitors, extends and ends a lab; gradebook, export and audit", async ({ page, browser }) => {
  test.setTimeout(300_000);
  // Student: start Mission 1, create the bucket from the CLI, check progress
  const sctx = await browser.newContext();
  const stu = await sctx.newPage();
  await signIn(stu, "demo-student3@cloudlabs.demo");
  await stu.getByTestId("lab-card").filter({ hasText: "Mission 1" }).click();
  await stu.getByTestId("start-lab").click();
  await stu.waitForURL(/\/play\?session=/);
  await expect(stu.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });
  await stu.getByTestId("tab-terminal").click();
  await expect(stu.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(stu, "aws s3 mb s3://cafe-demo03-site >/dev/null && echo MB_$((40+2))", "MB_42");
  await stu.getByTestId("check-progress").click();
  await expect(stu.getByTestId("progress-score")).not.toHaveText("0.00 / 100", { timeout: 60_000 });

  // Instructor: live view shows the student's latest progress
  await signIn(page, "demo-instructor@cloudlabs.demo");
  await page.getByTestId("course-card").filter({ hasText: "CLOUD-DEMO" }).getByRole("link", { name: "Live" }).click();
  const row = page.getByTestId("live-row").filter({ hasText: "Leo Student" });
  await expect(row).toBeVisible();
  await expect(row.getByTestId("live-progress")).toContainText("tasks");
  await page.screenshot({ path: "../../docs/screenshots/14-live-progress.png", fullPage: true });

  // Extend by 15 minutes, then end with grading
  await row.getByTestId("live-extend").click();
  await page.getByTestId("extend-minutes").selectOption("15");
  await page.getByTestId("action-reason").fill("network outage in lab 2");
  await page.getByTestId("action-confirm").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await row.getByTestId("live-end").click();
  await page.getByTestId("action-reason").fill("class ended");
  await page.getByTestId("action-confirm").click();
  await expect(page.getByTestId("live-row").filter({ hasText: "Leo Student" })).toHaveCount(0, { timeout: 90_000 });

  // The student's lab is over and graded
  await stu.waitForURL(/\/results\//, { timeout: 60_000 });  // the student lands on the graded result
  await expect(stu.getByTestId("final-score")).toContainText("/ 100");
  await sctx.close();

  // Gradebook → drill into the attempt's evidence
  await page.goto("/instructor");
  await page.getByTestId("course-card").filter({ hasText: "CLOUD-DEMO" }).getByRole("link", { name: "Gradebook" }).click();
  const gbRow = page.getByTestId("gradebook-row").filter({ hasText: "Leo Student" });
  await expect(gbRow).toBeVisible();
  const cell = gbRow.locator("a.gb-cell").first();
  await expect(cell).toContainText("/ 100");
  await page.screenshot({ path: "../../docs/screenshots/15-gradebook.png", fullPage: true });
  const download = page.waitForEvent("download");
  await page.getByTestId("export-gradebook").click();
  const csv = (await import("node:fs")).readFileSync((await (await download).path())!, "utf-8").replace(/^﻿/, "");
  expect(csv.split(/\r?\n/)[0]).toBe("student_name,email,student_id,course,assignment,lab,score,max_score,percentage,attempts_used,attempts_allowed,late,submitted_at,status");
  expect(csv).toContain("demo-student3@cloudlabs.demo,demo03,CLOUD-DEMO,Mission 1");
  await cell.click();
  await page.waitForURL(/\/instructor\/attempts\//);
  await expect(page.getByText("Ended by instructor").first()).toBeVisible();

  // Admin: audit log, users, runtime engines
  const actx = await browser.newContext();
  const adm = await actx.newPage();
  await signIn(adm, "demo-admin@cloudlabs.demo");
  await adm.waitForURL(/\/admin\/status/);
  await adm.goto("/admin/audit");
  await expect(adm.getByTestId("audit-row").filter({ hasText: "Ended Leo Student's lab and graded it" })).toBeVisible();
  await expect(adm.getByTestId("audit-row").filter({ hasText: "Gave Leo Student 15 more minutes" })).toContainText("network outage in lab 2");
  await adm.screenshot({ path: "../../docs/screenshots/16-audit-log.png", fullPage: true });
  await adm.goto("/admin/users");
  await expect(adm.getByTestId("user-row").filter({ hasText: "demo-student3@cloudlabs.demo" })).toBeVisible();
  await adm.goto("/admin/status");
  await expect(adm.getByText("floci · default").first()).toBeVisible({ timeout: 20_000 });  // one per runner
  await actx.close();
});

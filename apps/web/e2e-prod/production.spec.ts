import { expect, type Page, test } from "@playwright/test";
import { readFileSync } from "node:fs";

// Production smoke test: the first hour of a real deployment, through the browser only, over HTTPS.
// admin (first sign-in) → creates an instructor → instructor: course, roster, assignment of Mission 16 →
// new student: password change, console + terminal (WebSocket over TLS, audit proxy) → 100 → instructor sees it.
// It CREATES real accounts and a course named "Smoke test <stamp>" on the target; nothing is deleted or reset.
//
//   CLOUDLABS_ADMIN_EMAIL / CLOUDLABS_ADMIN_PASSWORD   the admin created as in DEPLOYMENT.md §2
//   CLOUDLABS_ADMIN_NEW_PASSWORD                        needed only if that admin still has to change the password

const ADMIN = process.env.CLOUDLABS_ADMIN_EMAIL ?? "";
const ADMIN_PW = process.env.CLOUDLABS_ADMIN_PASSWORD ?? "";
const LAB = "Mission 16: CloudCafé's audit trail";

async function signIn(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** First sign-in with a temporary password ends on the password page; choose the new one there. */
async function changePassword(page: Page, current: string, next: string) {
  await page.waitForURL(/\/account\/password/);
  await page.getByTestId("current-password").fill(current);
  await page.getByTestId("new-password").fill(next);
  await page.getByTestId("repeat-password").fill(next);
  await page.getByTestId("save-password").click();
  await page.waitForURL((u) => !u.pathname.startsWith("/account/password"));
}

async function termRun(page: Page, cmd: string, expectText: string) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 120_000 });
}

test("production: admin → instructor → course → student lab over HTTPS → graded", async ({ page, browser, baseURL }) => {
  test.setTimeout(900_000);
  expect(ADMIN && ADMIN_PW, "set CLOUDLABS_ADMIN_EMAIL and CLOUDLABS_ADMIN_PASSWORD").toBeTruthy();
  expect(baseURL!.startsWith("https://"), "production is served over HTTPS").toBeTruthy();
  const stamp = Date.now().toString(36).slice(-5);
  const domain = ADMIN.split("@")[1];

  // 0) The platform is healthy and demo accounts are refused
  const health = await page.request.get("/healthz");
  expect(await health.json()).toEqual({ database: true, runner: true });
  await signIn(page, "demo-student1@cloudlabs.demo", "cloudlabs-demo");
  await expect(page.getByRole("alert")).toBeVisible();

  // 1) Admin: first sign-in (password change if still temporary), then an instructor account
  await signIn(page, ADMIN, ADMIN_PW);
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  if (page.url().includes("/account/password")) {
    const next = process.env.CLOUDLABS_ADMIN_NEW_PASSWORD;
    expect(next, "the admin must change the password: set CLOUDLABS_ADMIN_NEW_PASSWORD").toBeTruthy();
    await changePassword(page, ADMIN_PW, next!);
  }
  await page.goto("/admin/users");
  await page.getByTestId("new-user").click();
  const instructor = `smoke-instructor-${stamp}@${domain}`;
  await page.getByLabel("Email").fill(instructor);
  await page.getByLabel("Name").fill(`Smoke Instructor ${stamp}`);
  await page.getByRole("dialog").getByLabel("Role").selectOption("instructor");
  await page.getByRole("button", { name: "Create account" }).click();
  const tmpInstructor = (await page.getByTestId("temp-password").locator("code").innerText()).trim();

  // 2) Instructor: course, roster with one new student, assignment of Mission 16
  const ictx = await browser.newContext({ ignoreHTTPSErrors: process.env.CLOUDLABS_INSECURE_TLS === "1" });
  const ins = await ictx.newPage();
  await signIn(ins, instructor, tmpInstructor);
  await changePassword(ins, tmpInstructor, `smoke-instructor-pw-${stamp}`);
  const CODE = `SMOKE-${stamp.toUpperCase()}`;
  await ins.goto("/instructor");
  await ins.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Courses" }).click();
  await ins.getByTestId("new-course").click();
  await ins.getByTestId("course-code").fill(CODE);
  await ins.getByTestId("course-title").fill(`Smoke test ${stamp}`);
  await ins.getByTestId("course-save").click();
  await ins.getByTestId("course-card").filter({ hasText: CODE }).getByTestId("course-link").click();
  const student = `smoke-student-${stamp}@${domain}`;
  await ins.getByTestId("roster-text").fill(`email,name\n${student},Smoke Student ${stamp}\n`);
  await ins.getByTestId("roster-preview").click();
  await expect(ins.getByTestId("roster-error-count")).toHaveText("0 with errors");
  await ins.getByTestId("roster-import-commit").click();
  await expect(ins.getByTestId("roster-result")).toContainText("1 new account created");
  const download = ins.waitForEvent("download");
  await ins.getByTestId("download-credentials").click();
  const csv = readFileSync((await (await download).path())!, "utf-8");
  const tmpStudent = csv.split(/\r?\n/).find((l) => l.includes(student))!.split(",")[2].replace(/"/g, "");
  await ins.getByTestId("new-assignment").click();
  const option = ins.getByTestId("asg-lab").locator("option", { hasText: LAB });
  await ins.getByTestId("asg-lab").selectOption((await option.first().getAttribute("value"))!);
  const ASG = `Smoke: audit trail ${stamp}`;
  await ins.getByTestId("asg-title").fill(ASG);
  await ins.getByTestId("asg-save").click();
  await expect(ins.getByTestId("assignment-link").filter({ hasText: ASG })).toBeVisible();

  // 3) Student: password change, console + terminal (WebSocket through TLS), audit-graded lab → 100
  const sctx = await browser.newContext({ ignoreHTTPSErrors: process.env.CLOUDLABS_INSECURE_TLS === "1" });
  const stu = await sctx.newPage();
  await signIn(stu, student, tmpStudent);
  await changePassword(stu, tmpStudent, `smoke-student-pw-${stamp}`);
  await stu.getByTestId("lab-card").filter({ hasText: CODE }).click();  // cards show the lab and the course code
  await stu.getByTestId("start-lab").click();
  await stu.waitForURL(/\/play\?session=/);
  await expect(stu.getByTestId("session-state")).toHaveText("Running", { timeout: 180_000 });
  const BUCKET = (await stu.getByTestId("task-create-bucket").innerText()).match(/cafe-[a-z0-9]+-ledger/)![0];
  await stu.getByTestId("open-create-bucket").click();
  await stu.getByTestId("new-bucket-name").fill(BUCKET);
  await stu.getByTestId("create-bucket").click();
  await expect(stu.getByText(`Successfully created bucket "${BUCKET}".`)).toBeVisible();
  await stu.getByRole("button", { name: BUCKET }).click();
  await stu.getByRole("tab", { name: "Properties" }).click();
  await stu.getByTestId("edit-versioning").click();
  await stu.getByTestId("versioning-enable").check();
  await stu.getByTestId("save-versioning").click();
  await expect(stu.getByTestId("versioning-status")).toHaveText("Enabled");
  await stu.getByTestId("tab-terminal").click();
  await expect(stu.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(stu, `echo date,total > ledger.csv && aws s3 cp ledger.csv s3://${BUCKET}/ledger.csv && echo SMOKE_$((40+2))`, "SMOKE_42");
  await stu.getByRole("tab", { name: "Console" }).click();
  await stu.getByTestId("check-progress").click();
  await expect(stu.getByTestId("progress-score")).toHaveText("100.00 / 100", { timeout: 120_000 });
  await stu.getByTestId("submit-lab").click();
  await stu.getByTestId("confirm-action").click();
  await stu.waitForURL(/\/results\//, { timeout: 180_000 });
  await expect(stu.getByTestId("final-score")).toHaveText("100.00 / 100");
  await sctx.close();

  // 4) Instructor sees the stored result
  await ins.getByTestId("assignment-link").filter({ hasText: ASG }).click();
  await expect(ins.getByTestId("result-row").filter({ hasText: `Smoke Student ${stamp}` })).toContainText("100.00");
  await ictx.close();
});

import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

// M43 instructor first-run journey: one instructor goes from an empty account to a graded student result
// using only the browser — no YAML, no shell, no database, no developer tooling. Every step below is a
// normal product surface; the only lab knowledge used is the bucket name the lab itself displays.

const PASSWORD = "cloudlabs-demo";
const shot = (page: import("@playwright/test").Page, name: string) =>
  page.screenshot({ path: `../../docs/screenshots/${name}.png`, fullPage: true });

async function signIn(page: import("@playwright/test").Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Edits autosave (M46), so by the time a test clicks Save the button may already be idle. Save if there is
 * anything to save, and always assert the draft really settled. */
async function saveDraft(page: import("@playwright/test").Page) {
  const btn = page.getByTestId("save-draft");
  const state = page.getByTestId("save-state");
  // Edits autosave ~800 ms after typing (M46), so the button may already be idle by the time we click —
  // and it can go idle *during* the click. Give the manual save a short leash and assert the outcome,
  // which is what the test actually cares about: the draft settled and nothing is left unsaved.
  if (await btn.isEnabled().catch(() => false)) {
    await btn.click({ timeout: 2_000 }).catch(() => undefined);
  }
  await expect(state).toHaveText("Saved", { timeout: 20_000 });
  await expect(btn).toBeDisabled();
}

test("instructor first run: course → roster → lab → publish → assign → student result", async ({ page, browser }) => {
  test.setTimeout(1_500_000);  // preview + a full test run in real sandboxes + a student lab
  const stamp = Date.now().toString(36).slice(-5).toUpperCase();
  const CODE = `FIRST-${stamp}`;
  const NEW = `ada.${stamp.toLowerCase()}@example.edu`;
  const LAB = `First-run S3 lab ${stamp}`;
  const ASG = `Week 1: first-run lab ${stamp}`;

  await signIn(page, "demo-instructor@cloudlabs.demo", PASSWORD);

  // 1) Create a course (instructors own their courses; no admin needed)
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Courses" }).click();
  await page.getByTestId("new-course").click();
  await page.getByTestId("course-code").fill(CODE);
  await page.getByTestId("course-title").fill("Cloud Computing First Run");
  await page.getByTestId("course-save").click();
  await page.getByTestId("course-card").filter({ hasText: CODE }).getByTestId("course-link").click();
  await expect(page.getByRole("heading", { name: new RegExp(CODE) })).toBeVisible();

  // 2) Import a roster: one brand-new student plus one existing demo student
  await page.getByTestId("roster-text").fill(
    `email,name\n${NEW},Ada New\ndemo-student2@cloudlabs.demo,Priya Student\n`);
  await page.getByTestId("roster-preview").click();
  await expect(page.getByTestId("roster-error-count")).toHaveText("0 with errors");
  await page.getByTestId("roster-import-commit").click();
  await expect(page.getByTestId("roster-result")).toContainText("1 new account created, 1 existing student enrolled");
  const download = page.waitForEvent("download");
  await page.getByTestId("download-credentials").click();
  const csv = readFileSync(await (await download).path()!, "utf-8");
  const TMP = csv.split(/\r?\n/).find((l) => l.includes(NEW))!.split(",")[2].replace(/"/g, "");
  await expect(page.getByTestId("roster-row").filter({ hasText: NEW })).toContainText("Awaiting first sign-in");
  await shot(page, "25-firstrun-course");

  // 3) Create a lab from a template (a working S3 lab, not a blank page)
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Labs", exact: true }).click();
  await page.getByTestId("new-lab").click();
  await page.getByTestId("template-s3-basics").click();
  await page.getByTestId("new-lab-title").fill(LAB);
  await page.getByTestId("new-lab-create").click();
  await page.waitForURL(/\/instructor\/labs\/drafts\//);
  await expect(page.getByTestId("draft-title")).toHaveText(LAB);
  await expect(page.getByTestId("validation-ok")).toBeVisible();

  // 4) Edit a task and add a check, entirely with generated forms
  await page.getByTestId("tab-tasks").click();
  const first = page.getByTestId("task-card").first();
  await first.getByTestId("task-title").fill("Create the {{ bucket }} bucket and turn on versioning");
  await first.getByTestId("add-check").click();
  const added = first.getByTestId("check-card").nth(1);
  await added.getByTestId("check-type").selectOption("s3.versioning");
  await added.getByTestId("param-bucket").fill("{{ bucket }}");
  await added.getByTestId("param-status").selectOption("Enabled");
  await saveDraft(page);
  await expect(page.getByTestId("validation-ok")).toBeVisible();
  await shot(page, "26-firstrun-builder");

  // 5) Configure the starting state with a typed break action (no shell anywhere)
  await page.getByTestId("tab-start").click();
  await page.getByTestId("make-break-fix").click();
  await page.getByTestId("add-break-action").click();
  await page.getByTestId("break-action-type").selectOption("s3.create_bucket");
  await page.getByTestId("param-bucket").fill("{{ bucket }}");
  await expect(page.getByTestId("broken-state")).toContainText("Bucket cafe-");
  await saveDraft(page);
  await shot(page, "27-firstrun-starting-state");

  // 6) Preview the broken sandbox, inspect it, reset it, stop it
  await page.getByTestId("open-preview-sandbox").click();
  await page.waitForURL(/\/preview$/);
  await page.getByTestId("preview-start").click();
  await expect(page.getByTestId("preview-status")).toContainText("Running", { timeout: 120_000 });
  await expect(page.locator(".console")).toBeVisible();
  await page.getByTestId("preview-reset").click();
  await expect(page.getByTestId("preview-status")).toContainText("Running", { timeout: 120_000 });
  await page.getByTestId("preview-stop").click();
  await expect(page.getByTestId("preview-status")).toHaveText("Stopped", { timeout: 60_000 });
  await page.getByRole("link", { name: "← Back to the draft" }).click();

  // 7) Readiness → test in real sandboxes → publish
  await page.getByTestId("tab-test").click();
  await expect(page.getByTestId("readiness-status")).toHaveText("Not ready");
  await page.getByTestId("run-test").click();
  await expect(page.getByTestId("test-status")).toHaveText("Passed", { timeout: 900_000 });
  await expect(page.getByTestId("readiness-status")).toHaveText("Ready to publish");
  await shot(page, "28-firstrun-readiness");
  await page.getByTestId("publish").click();
  await expect(page.getByTestId("published-banner")).toBeVisible();

  // 8) Assign the published lab to the course
  await page.goto("/instructor");
  await page.getByTestId("course-card").filter({ hasText: CODE }).getByTestId("course-link").click();
  await page.getByTestId("new-assignment").click();
  await page.getByTestId("asg-lab").selectOption({ label: `${LAB} · v1.0.0` });
  await page.getByTestId("asg-title").fill(ASG);
  await page.getByTestId("asg-save").click();
  await expect(page.getByTestId("assignment-link").filter({ hasText: ASG })).toBeVisible();

  // 9) The new student changes their temporary password, then completes the lab in the console only
  const sctx = await browser.newContext();
  const stu = await sctx.newPage();
  await signIn(stu, NEW, TMP);
  await stu.waitForURL(/\/account\/password/);
  await stu.getByTestId("current-password").fill(TMP);
  await stu.getByTestId("new-password").fill("first-run-password-1");
  await stu.getByTestId("repeat-password").fill("first-run-password-1");
  await stu.getByTestId("save-password").click();
  await stu.waitForURL(/\/labs/);
  await stu.getByTestId("lab-card").filter({ hasText: LAB }).click();
  await stu.getByTestId("start-lab").click();
  await stu.waitForURL(/\/play\?session=/);
  await expect(stu.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  const BUCKET = (await stu.getByTestId("task-create-bucket").innerText()).match(/cafe-[a-z0-9]+-site/)![0];
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
  await stu.getByRole("tab", { name: "Objects" }).click();
  await stu.getByTestId("open-upload").click();
  await stu.getByTestId("upload-input").setInputFiles({
    name: "index.html", mimeType: "text/html", buffer: Buffer.from("<h1>Ada's cafe</h1>") });
  await stu.getByTestId("confirm-upload").click();
  await expect(stu.getByText(/Upload succeeded/)).toBeVisible();
  await stu.getByRole("tab", { name: "Properties" }).click();
  await stu.getByTestId("edit-tags").click();
  await stu.getByTestId("add-tag").click();
  await stu.getByLabel("Tag key").fill("project");
  await stu.getByLabel("Tag value").fill("cloudcafe");
  await stu.getByTestId("save-tags").click();
  await expect(stu.getByText("Successfully edited tags.")).toBeVisible();

  await stu.getByTestId("check-progress").click();
  await expect(stu.getByTestId("progress-score")).toHaveText("100.00 / 100");
  await stu.getByTestId("submit-lab").click();
  await stu.getByTestId("confirm-action").click();
  await stu.waitForURL(/\/results\//, { timeout: 120_000 });
  await expect(stu.getByTestId("final-score")).toHaveText("100.00 / 100");
  await sctx.close();

  // 10) The instructor sees the stored result and drills into the evidence
  await page.getByTestId("assignment-link").filter({ hasText: ASG }).click();
  const row = page.getByTestId("result-row").filter({ hasText: "Ada New" });
  await expect(row).toContainText("100.00");
  await row.getByRole("link", { name: /#1:/ }).click();
  await page.waitForURL(/\/instructor\/attempts\//);
  await expect(page.getByTestId("instructor-score")).toContainText("100.00");
  await expect(page.getByTestId("evidence-check").first()).toBeVisible();
  await shot(page, "29-firstrun-result");
});

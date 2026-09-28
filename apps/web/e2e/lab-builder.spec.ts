import { expect, type Page, test } from "@playwright/test";

// Phase 8 Lab Builder (docs/NEXT.md milestone 38): the instructor clones Mission 1, changes a task, tests it in
// real sandboxes (untouched 0, partial 50, solution 100 on every engine), publishes it, assigns it to the demo
// course, and a student starts it.

const PASSWORD = "cloudlabs-demo";
const NEW_TITLE = "Create the café's S3 bucket {{ bucket }}";
const ASSIGNMENT = "Builder mission";
const shot = (page: Page, name: string) => page.screenshot({ path: `../../docs/screenshots/${name}.png`, fullPage: true });

/** Edits autosave (M46), so by the time a test clicks Save the button may already be idle. Save if there is
 * anything to save, and always assert the draft really settled. */
async function saveDraft(page: Page) {
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

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("instructor clones, tests and publishes a lab; a student starts it", async ({ page, browser }) => {
  test.setTimeout(900_000);  // six real sandboxes, one after another

  // Clone the built-in Mission 1 from the lab library
  await signIn(page, "demo-instructor@cloudlabs.demo");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Labs", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Labs", exact: true })).toBeVisible();
  const mission = page.getByTestId("builtin-labs").getByTestId("lab-row").filter({ hasText: "Mission 1" });
  await mission.getByTestId("clone-lab").click();
  await page.waitForURL(/\/instructor\/labs\/drafts\//);
  await expect(page.getByTestId("draft-title")).toHaveText(/Mission 1.*\(copy\)/);
  await expect(page.getByTestId("validation-ok")).toBeVisible();
  await shot(page, "20-builder-overview");

  // Change the first task's title (kept as a variable template) and save
  await page.getByTestId("tab-tasks").click();
  const first = page.getByTestId("task-card").first();
  await first.getByTestId("task-title").fill(NEW_TITLE);
  await expect(first.getByTestId("check-card").first().getByTestId("check-type")).toHaveValue("s3.bucket_exists");
  await shot(page, "21-builder-tasks");
  await saveDraft(page);
  await expect(page.getByTestId("validation-ok")).toBeVisible();

  // The student preview shows the rendered task, never the checks
  await page.getByTestId("tab-preview").click();
  await expect(page.getByTestId("preview")).toContainText("Create the café's S3 bucket cafe-");
  await expect(page.getByTestId("preview")).not.toContainText("s3.bucket_exists");

  // YAML view reflects the saved change
  await page.getByTestId("tab-yaml").click();
  await expect(page.getByTestId("yaml-text")).toHaveValue(/Create the café's S3 bucket/);

  // Test in real sandboxes: 0 / 50 / 100 on every engine, then publish
  await page.getByTestId("tab-test").click();
  await expect(page.getByTestId("publish")).toBeDisabled();
  await page.getByTestId("run-test").click();
  await expect(page.getByTestId("draft-status")).toHaveText("Testing…");
  await expect(page.getByTestId("test-status")).toHaveText("Passed", { timeout: 840_000 });
  const scores = page.getByTestId("scenario-row");
  for (const engine of ["moto", "floci"]) {
    await expect(page.locator(`[data-scenario="${engine}/empty"] [data-testid="scenario-score"]`)).toHaveText("0.00");
    await expect(page.locator(`[data-scenario="${engine}/partial"] [data-testid="scenario-score"]`)).toHaveText("50.00");
    await expect(page.locator(`[data-scenario="${engine}/solution"] [data-testid="scenario-score"]`)).toHaveText("100.00");
  }
  expect(await scores.count()).toBe(6);
  await shot(page, "22-builder-test-passed");
  await page.getByTestId("publish").click();
  await expect(page.getByTestId("published-banner")).toBeVisible();
  await expect(page.getByTestId("draft-status")).toHaveText("Published");

  // Assign the published lab to the demo course
  await page.goto("/instructor");
  await page.getByTestId("course-card").filter({ hasText: "CLOUD-DEMO" }).getByTestId("course-link").click();
  await page.getByTestId("new-assignment").click();
  const option = page.getByTestId("asg-lab").locator("option", { hasText: "(copy)" });
  await page.getByTestId("asg-lab").selectOption(await option.getAttribute("value") ?? "");
  await page.getByTestId("asg-title").fill(ASSIGNMENT);
  await page.getByTestId("asg-save").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText(ASSIGNMENT)).toBeVisible();

  // A student starts it and sees the changed task
  const sctx = await browser.newContext();
  const stu = await sctx.newPage();
  await signIn(stu, "demo-student3@cloudlabs.demo");
  await stu.getByTestId("lab-card").filter({ hasText: "Mission 1: CloudCafé goes online (copy)" }).click();  // cards show the lab title
  await expect(stu.getByText(/Create the café's S3 bucket cafe-demo03/)).toBeVisible();
  await stu.getByTestId("start-lab").click();
  await stu.waitForURL(/\/play\?session=/);
  await expect(stu.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });
  // End it without grading so later specs start from a clean slate
  await stu.getByRole("button", { name: "End lab" }).click();
  await stu.getByTestId("confirm-action").click();
  await sctx.close();
});

// Phase 9 milestone 40: the New-lab gallery starts a fresh lab from a curated template (no YAML needed).
test("instructor starts a lab from a template", async ({ page }) => {
  await signIn(page, "demo-instructor@cloudlabs.demo");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Labs", exact: true }).click();
  await page.getByTestId("new-lab").click();
  await expect(page.getByTestId("template-gallery")).toBeVisible();
  await page.getByTestId("template-s3-basics").click();
  await expect(page.getByTestId("new-lab-title")).toHaveValue("S3 basics");
  await page.getByTestId("new-lab-title").fill("Template lab");
  await page.getByTestId("new-lab-create").click();
  await page.waitForURL(/\/instructor\/labs\/drafts\//);
  await expect(page.getByTestId("draft-title")).toHaveText("Template lab");
  await expect(page.getByTestId("validation-ok")).toBeVisible();
  await page.getByTestId("tab-tasks").click();
  await expect(page.getByTestId("task-card").first().getByTestId("task-title")).toHaveValue(/Create the S3 bucket/);
});

// Phase 9 milestone 41: a break-fix starting state is authored with typed actions, never shell.
test("instructor authors a break-fix starting state with typed actions", async ({ page }) => {
  await signIn(page, "demo-instructor@cloudlabs.demo");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Labs", exact: true }).click();
  await page.getByTestId("new-lab").click();
  await page.getByTestId("new-lab-title").fill("Broken bucket lab");
  await page.getByTestId("new-lab-create").click();
  await page.waitForURL(/\/instructor\/labs\/drafts\//);

  await page.getByTestId("tab-start").click();
  await page.getByTestId("make-break-fix").click();
  await page.getByTestId("add-break-action").click();
  await page.getByTestId("break-action-type").selectOption("s3.create_bucket");
  await page.getByTestId("param-bucket").fill("{{ bucket }}");
  await expect(page.getByTestId("broken-state")).toContainText("Bucket lab-");
  await expect(page.getByTestId("baseline-score")).toHaveValue("0");
  await saveDraft(page);
  await expect(page.getByTestId("validation-ok")).toBeVisible();
});

// Phase 9 milestone 42: preview the authored starting state in a real sandbox, inspect it, reset and stop,
// and see the publish-readiness checklist that gates publishing.
test("instructor previews the starting state and sees the publish readiness", async ({ page }) => {
  test.setTimeout(300_000);
  await signIn(page, "demo-instructor@cloudlabs.demo");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Labs", exact: true }).click();
  await page.getByTestId("new-lab").click();
  await page.getByTestId("new-lab-title").fill("Preview walkthrough");
  await page.getByTestId("new-lab-create").click();
  await page.waitForURL(/\/instructor\/labs\/drafts\//);

  // the readiness checklist is visible and clearly not ready before a test run
  await page.getByTestId("tab-test").click();
  await expect(page.getByTestId("readiness")).toBeVisible();
  await expect(page.getByTestId("readiness-status")).toHaveText("Not ready");
  await expect(page.getByTestId("readiness-baseline")).toContainText("not run yet");
  await expect(page.getByTestId("publish")).toBeDisabled();

  // author a break-fix starting state, then launch the preview sandbox
  await page.getByTestId("tab-start").click();
  await page.getByTestId("make-break-fix").click();
  await page.getByTestId("add-break-action").click();
  await page.getByTestId("break-action-type").selectOption("s3.create_bucket");
  await page.getByTestId("param-bucket").fill("{{ bucket }}");
  await saveDraft(page);
  await page.getByTestId("open-preview-sandbox").click();
  await page.waitForURL(/\/preview$/);

  await expect(page.getByTestId("preview-status")).toHaveText("Stopped");
  await page.getByTestId("preview-start").click();
  await expect(page.getByTestId("preview-status")).toContainText("Running", { timeout: 120_000 });
  await expect(page.locator(".console")).toBeVisible();
  await page.screenshot({ path: "../../docs/screenshots/24-preview-sandbox.png", fullPage: true });
  await page.getByTestId("preview-tab-terminal").click();
  await expect(page.locator(".xterm")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("preview-tab-console").click();
  await page.getByTestId("preview-reset").click();
  await expect(page.getByTestId("preview-status")).toContainText("Running", { timeout: 120_000 });
  await page.getByTestId("preview-stop").click();
  await expect(page.getByTestId("preview-status")).toHaveText("Stopped", { timeout: 60_000 });
});

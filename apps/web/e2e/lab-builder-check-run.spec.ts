import { expect, type Page, test } from "@playwright/test";

// Phase 10, milestone 47 — the instructor runs ONE grading check against the draft's preview sandbox and
// sees the grader's own answer. The state that makes it pass is created through the product's own console.

const PASSWORD = "cloudlabs-demo";
const BUCKET = "runcheck-target-bucket";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("an author runs a single check against the preview sandbox and sees the grader's answer", async ({ page }) => {
  test.setTimeout(300_000);

  await signIn(page, "demo-instructor@cloudlabs.demo");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Labs", exact: true }).click();
  const mission = page.getByTestId("builtin-labs").getByTestId("lab-row").filter({ hasText: "Mission 1" });
  await mission.getByTestId("clone-lab").click();
  await page.waitForURL(/\/instructor\/labs\/drafts\//);
  const draftUrl = page.url();

  await page.getByTestId("tab-tasks").click();
  // every check card offers its own runner, so scope to the first one (s3.bucket_exists)
  const card = page.getByTestId("check-card").first();
  const run = card.getByTestId("run-check");

  await card.getByTestId("param-bucket").fill(BUCKET);
  await expect(page.getByTestId("save-state")).toHaveText("Saved", { timeout: 20_000 });

  // No preview sandbox yet: the run button is off and says what to do about it.
  await expect(run).toBeDisabled();
  await expect(card.getByTestId("run-check-hint")).toBeVisible();

  // Launch the preview sandbox (a real, isolated sandbox built from the draft's starting state).
  await page.goto(`${draftUrl}/preview`);
  await page.getByTestId("preview-start").click();
  await expect(page.getByTestId("preview-status")).toContainText("Running", { timeout: 120_000 });

  // Empty starting state → the check fails and the panel says exactly what the grader saw.
  await page.goto(draftUrl);
  await page.getByTestId("tab-tasks").click();
  const cardA = page.getByTestId("check-card").first();
  await expect(cardA.getByTestId("run-check")).toBeEnabled();
  await cardA.getByTestId("run-check").click();
  const failed = cardA.getByTestId("check-run-result");
  await expect(failed).toBeVisible({ timeout: 60_000 });
  await expect(failed).toHaveAttribute("data-passed", "false");
  await expect(cardA.getByTestId("run-expected")).toHaveText("exists");
  await expect(cardA.getByTestId("run-actual")).toHaveText("missing");
  await expect(cardA.getByTestId("run-message")).toContainText("was not found");
  await expect(failed).toContainText("marks possible");
  await expect(failed).toContainText("s3.bucket_exists");

  // Do the work through the console, exactly as a student would.
  await page.goto(`${draftUrl}/preview`);
  await page.getByTestId("svc-s3").click();
  await page.getByTestId("open-create-bucket").click();
  await page.getByTestId("new-bucket-name").fill(BUCKET);
  await page.getByTestId("create-bucket").click();
  await expect(page.getByText(`Successfully created bucket "${BUCKET}".`)).toBeVisible();

  // Run the same check again: same code, new evidence → it passes.
  await page.goto(draftUrl);
  await page.getByTestId("tab-tasks").click();
  const cardB = page.getByTestId("check-card").first();
  await page.waitForTimeout(1_200);   // stay inside the run spacing
  await cardB.getByTestId("run-check").click();
  const passed = cardB.getByTestId("check-run-result");
  await expect(passed).toBeVisible({ timeout: 60_000 });
  await expect(passed).toHaveAttribute("data-passed", "true");
  await expect(cardB.getByTestId("run-actual")).toHaveText("exists");

  // Nothing was graded: this is a preview, not an attempt.
  await page.goto(`${draftUrl}/preview`);
  await page.getByTestId("preview-stop").click();
  await expect(page.getByTestId("preview-status")).toHaveText("Stopped");
});

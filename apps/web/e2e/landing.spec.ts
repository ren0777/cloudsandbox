import { expect, test } from "@playwright/test";

// Public marketing site at / (Stackora). The authenticated application stays behind /login.
test("landing page presents Stackora and its CTAs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Stackora", level: 1 })).toBeVisible();
  await expect(page.getByText("Launch it. Break it. Fix it.")).toBeVisible();
  await expect(page.getByText("Hands-on cloud labs with real CLI workflows and instant grading.").first()).toBeVisible();
  await expect(page.getByTestId("cta-primary")).toBeVisible();
  await expect(page.getByTestId("cta-instructor")).toBeVisible();
  await expect(page.getByText("Supported AWS services")).toBeVisible();
  await expect(page.getByText("Instructor Lab Builder").first()).toBeVisible();
  await expect(page.getByText("Apache-2.0. Yours to run.")).toBeVisible();
  await page.screenshot({ path: "../../docs/screenshots/23-landing.png", fullPage: true });
});

test("landing CTAs reach the login page", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("cta-try").click();
  await page.waitForURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

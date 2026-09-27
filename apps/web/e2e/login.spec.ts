import { expect, test } from "@playwright/test";

// Demo Mode (PLAN §16): the login page lists the seeded demo accounts and signs in with one click.
// The API returns none when CL_DEMO_MODE is off or the demo reset has not run, so this is a demo-only UI.
test("demo accounts sign in with one click", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByTestId("demo-logins")).toBeVisible();
  await expect(page.getByTestId("demo-logins")).toContainText("cloudlabs-demo");
  await page.getByTestId("demo-login-demo-instructor").click();
  await page.waitForURL(/\/instructor/);
  await expect(page.getByRole("banner")).toContainText("Dr. Ira Instructor");
});

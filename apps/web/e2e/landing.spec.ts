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

// Signed-in visitors must not be told to sign in: the landing header shows their account and a link back to
// their role's home, and the app-shell brand returns to that home instead of the marketing page.
test("signed-in visitors see their account, not the sign-in CTAs", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("demo-login-demo-instructor").click();
  await page.waitForURL(/\/instructor/);

  // The shell brand is an in-app link now, not a trip back to the marketing page.
  await page.getByRole("link", { name: "Stackora" }).click();
  await expect(page).toHaveURL(/\/instructor$/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Reaching the marketing page directly while signed in shows the account, not Sign in / Try the demo.
  await page.goto("/");
  await expect(page.getByTestId("landing-user")).toContainText("Dr. Ira Instructor");
  await expect(page.getByTestId("cta-try")).toHaveCount(0);
  await expect(page.getByTestId("cta-primary")).toHaveCount(0);
  await expect(page.getByTestId("cta-instructor")).toHaveCount(0);
  await expect(page.getByTestId("cta-primary-home")).toBeVisible();
  await expect(page.getByTestId("cta-final-home")).toBeVisible();
});

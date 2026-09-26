import { expect, test } from "@playwright/test";

// An admin creates a course from "Courses & staff" and assigns its first instructor in the same step.
test("admin creates a course with an instructor", async ({ page }) => {
  const code = `ADM-${Date.now().toString(36).slice(-5)}`.toUpperCase();
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-admin@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/admin\/status/);
  await page.getByRole("link", { name: "Courses & staff" }).click();
  await page.getByTestId("admin-new-course").click();
  await page.getByTestId("nc-code").fill(code);
  await page.getByTestId("nc-title").fill("Cloud Computing (Fall)");
  await page.getByTestId("nc-instructor").fill("demo-instructor@cloudlabs.demo");
  await page.getByTestId("nc-save").click();
  const row = page.getByRole("row").filter({ hasText: code });
  await expect(row).toContainText("Dr. Ira Instructor");
  await expect(row).toContainText("0");
});

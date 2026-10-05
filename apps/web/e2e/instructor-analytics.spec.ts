import { expect, type Page, test } from "@playwright/test";

// Phase 10, milestone 49 — the instructor's analytics view.
//
// The demo course is shared with every other spec, so by the time this file runs in a full suite other
// students have already submitted: test 1 therefore asserts the *structure* only. The empty states are
// asserted on a course this file creates itself, so they hold regardless of spec ordering.

const PASSWORD = "cloudlabs-demo";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function openCourse(page: Page, code: string) {
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Courses", exact: true }).click();
  await page.getByTestId("course-card").filter({ hasText: code }).getByTestId("course-link").click();
  await page.waitForURL(/\/instructor\/courses\//);
}

test("instructor opens course analytics: metrics, assignment table and ranked views", async ({ page }) => {
  await signIn(page, "demo-instructor@cloudlabs.demo");
  await openCourse(page, "CLOUD-DEMO");

  const link = page.getByTestId("open-analytics");
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL(/\/analytics$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("CLOUD-DEMO");
  await page.screenshot({ path: "../../docs/screenshots/36-course-analytics.png", fullPage: true });

  // headline metrics, each labelled
  expect(await page.getByTestId("stat").count()).toBeGreaterThanOrEqual(5);
  for (const label of ["Students", "Submitted", "Average score", "Late", "Interrupted"]) {
    await expect(page.getByTestId(`stat-${label.toLowerCase().replace(/\s+/g, "-")}`)).toBeVisible();
  }
  // interruptions are called out as the platform's problem, not the student's
  await expect(page.getByText("platform failures — not student mistakes")).toBeVisible();

  // the assignment table lists the seeded labs (with or without submissions by now)
  await expect(page.getByTestId("analytics-assignments")).toBeVisible();
  expect(await page.getByTestId("assignment-stat").count()).toBeGreaterThan(0);

  // both ranked views are present — with rows, or with their own honest empty state
  await expect(page.getByTestId("most-failed-tasks")).toBeVisible();
  await expect(page.getByTestId("most-missed-checks")).toBeVisible();
  await expect(page.getByText("an interrupted lab is listed under", { exact: false })).toBeVisible();

  // the table exports as CSV: one row per lab plus the "All labs" totals row
  const download = page.waitForEvent("download");
  await page.getByTestId("export-analytics").click();
  const csv = (await import("node:fs")).readFileSync((await (await download).path())!, "utf-8").replace(/^﻿/, "");
  const lines = csv.trim().split(/\r?\n/);
  expect(lines[0]).toBe("course_code,assignment,lab,max_score,students,submitted,submission_rate_pct,counted_attempts,avg_attempts_used,avg_score,avg_completion_minutes,late_submissions,interruptions,interruption_reasons");
  expect(lines.length).toBe(await page.getByTestId("assignment-stat").count() + 2);
  expect(lines[lines.length - 1]).toContain("CLOUD-DEMO,All labs");

  // back to the course
  await page.getByRole("link", { name: /← CLOUD-DEMO/ }).click();
  await page.waitForURL(/\/instructor\/courses\/[^/]+$/);
});

test("a course this file creates shows both analytics empty states", async ({ page }) => {
  await signIn(page, "demo-instructor@cloudlabs.demo");

  // 1) a course with no labs at all
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Courses", exact: true }).click();
  await page.getByTestId("new-course").click();
  await page.getByTestId("course-code").fill("EMPTY-AN");
  await page.getByTestId("course-title").fill("No labs yet");
  await page.getByTestId("course-save").click();
  await page.getByTestId("course-card").filter({ hasText: "EMPTY-AN" }).getByTestId("course-link").click();
  await page.waitForURL(/\/instructor\/courses\//);

  await page.getByTestId("open-analytics").click();
  await page.waitForURL(/\/analytics$/);
  await expect(page.getByTestId("analytics-empty")).toContainText("No labs assigned to this course yet");
  await expect(page.getByTestId("analytics-assignments")).toHaveCount(0);

  // 2) …then give it one assignment and nobody's work: the "nothing submitted" states
  await page.getByRole("link", { name: /← EMPTY-AN/ }).click();
  await page.waitForURL(/\/instructor\/courses\/[^/]+$/);
  await page.getByTestId("new-assignment").click();
  await page.getByTestId("asg-lab").selectOption({ index: 0 });
  await page.getByTestId("asg-title").fill("Analytics probe");
  await page.getByTestId("asg-save").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.getByTestId("open-analytics").click();
  await page.waitForURL(/\/analytics$/);
  await expect(page.getByTestId("analytics-empty")).toHaveCount(0);
  await expect(page.getByTestId("assignment-stat")).toHaveCount(1);
  await expect(page.getByTestId("stat-submitted")).toHaveText("0");
  await expect(page.getByTestId("analytics-assignments")).toContainText("Nobody has submitted yet");
  await expect(page.getByTestId("most-failed-tasks")).toContainText("No task has been failed by anyone yet.");
  await expect(page.getByTestId("most-missed-checks")).toContainText("No check has been failed by anyone yet.");
});

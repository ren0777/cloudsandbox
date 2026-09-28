import { expect, type Page, test } from "@playwright/test";

// Phase 10, milestone 46: the Lab Builder keeps a teacher's work. Edits autosave, undo/redo walks them,
// a failed save says so instead of failing silently, and a stale save refuses to overwrite newer content.

const PASSWORD = "cloudlabs-demo";
const DRAFT_PUT = /\/api\/instructor\/builder\/drafts\/[0-9a-f-]{36}$/;

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Sign in and clone Mission 1 — a draft to edit, without running any sandbox. */
async function openDraft(page: Page) {
  await signIn(page, "demo-instructor@cloudlabs.demo");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Labs", exact: true }).click();
  const mission = page.getByTestId("builtin-labs").getByTestId("lab-row").filter({ hasText: "Mission 1" });
  await mission.getByTestId("clone-lab").click();
  await page.waitForURL(/\/instructor\/labs\/drafts\//);
  await expect(page.getByTestId("draft-title")).toBeVisible();
  await expect(page.getByTestId("save-state")).toHaveCount(0);   // nothing loaded as unsaved
}

const stubPut = (page: Page, status: number, body: Record<string, unknown>, onCall?: (n: number) => void) => {
  let calls = 0;
  return page.route(DRAFT_PUT, async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    calls += 1;
    onCall?.(calls);
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
};

test("an edit autosaves, survives a tab switch and a reload, and needs no Save click", async ({ page }) => {
  await openDraft(page);
  const title = page.getByTestId("lab-title");
  const before = await title.inputValue();
  const after = `${before} (autosaved)`;

  await title.fill(after);
  await expect(page.getByTestId("save-state")).toHaveText(/Unsaved changes|Saving…/);
  await expect(page.getByTestId("save-state")).toHaveText("Saved", { timeout: 20_000 });
  await expect(page.getByTestId("save-draft")).toBeDisabled();     // nothing left to save by hand

  // switching tabs must not discard anything (the content is still in memory)
  await page.getByTestId("tab-tasks").click();
  await page.getByTestId("tab-overview").click();
  await expect(title).toHaveValue(after);

  // …and a full reload shows the autosaved content, not the old one
  await page.reload();
  await expect(page.getByTestId("lab-title")).toHaveValue(after);
});

test("undo and redo walk the edits, and the saved state follows", async ({ page }) => {
  await openDraft(page);
  const title = page.getByTestId("lab-title");
  const before = await title.inputValue();

  await expect(page.getByTestId("undo-draft")).toBeDisabled();    // nothing to undo yet
  await title.fill(`${before} one`);
  await expect(page.getByTestId("undo-draft")).toBeEnabled();

  await page.getByTestId("undo-draft").click();
  await expect(title).toHaveValue(before);
  await expect(page.getByTestId("undo-draft")).toBeDisabled();    // back at the baseline

  await page.getByTestId("redo-draft").click();
  await expect(title).toHaveValue(`${before} one`);
  await expect(page.getByTestId("redo-draft")).toBeDisabled();

  // the undone-then-redone content autosaves like any other edit
  await expect(page.getByTestId("save-state")).toHaveText("Saved", { timeout: 20_000 });
});

test("a failed save is reported and retried by the teacher, not hammered by the app", async ({ page }) => {
  await openDraft(page);
  let puts = 0;
  await stubPut(page, 500, { error: { code: "internal_error", message: "boom", request_id: "req" } },
    () => { puts += 1; });

  await page.getByTestId("lab-title").fill("This save will fail");
  await expect(page.getByTestId("save-failed")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("save-state")).toHaveText("Save failed");
  await expect(page.getByTestId("stale-banner")).toHaveCount(0);
  await page.waitForTimeout(2_500);
  expect(puts).toBe(1);                                           // one attempt: no automatic retry loop

  await page.unroute(DRAFT_PUT);
  await page.getByTestId("save-retry").click();
  await expect(page.getByTestId("save-state")).toHaveText("Saved", { timeout: 20_000 });
  await page.reload();
  await expect(page.getByTestId("lab-title")).toHaveValue("This save will fail");
});

test("a stale save never overwrites newer content", async ({ page }) => {
  await openDraft(page);
  await stubPut(page, 409, {
    error: { code: "stale_revision",
      message: "this draft was changed somewhere else (another tab, or a test run); reload it so your changes don't overwrite the newer version",
      request_id: "req", rev: "0".repeat(64) },
  });

  await page.getByTestId("lab-title").fill("Would clobber the other tab");
  await expect(page.getByTestId("stale-banner")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("save-failed")).toHaveCount(0);   // the stale banner explains it instead
  await expect(page.getByTestId("lab-title")).toHaveValue("Would clobber the other tab");  // kept locally

  await page.unroute(DRAFT_PUT);
  await page.getByTestId("stale-reload").click();
  await expect(page.getByTestId("stale-banner")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId("save-state")).toHaveCount(0);    // reloaded: nothing dangling
});

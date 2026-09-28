import { expect, type Page, test } from "@playwright/test";

// M44 SQS: Mission 10 is built in the SQS console (queue with a real retention policy, first order on
// the queue) and Mission 11's misconfigured queue is repaired from its Attributes tab.
// Runs on the compose stack with demo data (CLOUDLABS_URL, default http://localhost:3000).

const PASSWORD = "cloudlabs-demo";
const shot = (page: Page, name: string) => page.screenshot({ path: `../../docs/screenshots/${name}.png` });

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function startLab(page: Page, mission: string, timeout = 120_000) {
  await page.getByTestId("lab-card").filter({ hasText: mission }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout });
}

test.describe.serial("SQS labs in the console", () => {
  test("Mission 10: create the order queue and score 100", async ({ page }) => {
    test.setTimeout(600_000);
    await signIn(page, "demo-student1@cloudlabs.demo");
    await startLab(page, "Mission 10");

    // The SQS console is the initial service of an sqs lab.
    await expect(page.getByTestId("sqs-open-create")).toBeVisible();
    await page.getByTestId("sqs-open-create").click();
    await page.getByTestId("sqs-name").fill("cafe-orders-demo01");
    await page.getByTestId("sqs-retention").fill("3600");
    await page.getByTestId("sqs-create-save").click();
    await expect(page.getByText("Successfully created queue cafe-orders-demo01.")).toBeVisible();
    await page.getByTestId("sqs-row").filter({ hasText: "cafe-orders-demo01" }).getByTestId("sqs-open-detail").click();

    // Send the first order, then poll to prove it is really on the queue.
    await page.getByTestId("sqs-tab-send").click();
    await page.getByTestId("sqs-message-body").fill('{"orderId": 1001, "drink": "latte"}');
    await page.getByTestId("sqs-send").click();
    await expect(page.getByText("Message sent.")).toBeVisible();
    await page.getByTestId("sqs-tab-messages").click();
    await page.getByTestId("sqs-poll").click();
    await expect(page.getByTestId("sqs-message").first()).toContainText("latte");
    await shot(page, "32-sqs-console");

    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
    await page.getByTestId("submit-lab").click();
    await page.getByTestId("confirm-action").click();
    await page.waitForURL(/\/results\//, { timeout: 120_000 });
    await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  });

  test("Mission 11: unstuck the queue's settings", async ({ page }) => {
    test.setTimeout(600_000);
    await signIn(page, "demo-student2@cloudlabs.demo");
    await startLab(page, "Mission 11");

    await page.getByTestId("sqs-row").filter({ hasText: "cafe-orders-demo02" }).getByTestId("sqs-open-detail").click();
    await page.getByTestId("sqs-tab-attributes").click();
    await expect(page.getByTestId("sqs-attr-visibility")).toHaveValue("43200");
    await expect(page.getByTestId("sqs-attr-delay")).toHaveValue("900");
    await page.getByTestId("sqs-attr-visibility").fill("30");
    await page.getByTestId("sqs-attr-delay").fill("0");
    await page.getByTestId("sqs-save-attributes").click();
    await expect(page.getByText("Queue attributes saved.")).toBeVisible();
    await shot(page, "33-sqs-breakfix");

    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
    await page.getByTestId("submit-lab").click();
    await page.getByTestId("confirm-action").click();
    await page.waitForURL(/\/results\//, { timeout: 120_000 });
    await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  });
});

import { expect, type Page, test } from "@playwright/test";

// M44 SNS: Mission 12 builds a fan-out (queue + topic + subscription + publish) in the console, and
// Mission 13 restores a deleted subscription. Delivery is proven by polling the SQS queue.
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

test.describe.serial("SNS labs in the console", () => {
  test("Mission 12: build fan-out to a queue and score 100", async ({ page }) => {
    test.setTimeout(600_000);
    await signIn(page, "demo-student1@cloudlabs.demo");
    await startLab(page, "Mission 12");

    // A qs+sns lab starts on the SQS console: create the queue first.
    await page.getByTestId("sqs-open-create").click();
    await page.getByTestId("sqs-name").fill("cafe-orders-demo01");
    await page.getByTestId("sqs-create-save").click();
    await expect(page.getByText("Successfully created queue cafe-orders-demo01.")).toBeVisible();

    // Switch to SNS: create the topic with its display name.
    await page.getByTestId("svc-sns").click();
    await page.getByTestId("sns-open-create").click();
    await page.getByTestId("sns-name").fill("cafe-alerts-demo01");
    await page.getByTestId("sns-display-name").fill("CloudCafé alerts");
    await page.getByTestId("sns-create-save").click();
    await expect(page.getByText("Successfully created topic cafe-alerts-demo01.")).toBeVisible();

    // Subscribe the queue, then publish an alert.
    await page.getByTestId("sns-row").filter({ hasText: "cafe-alerts-demo01" }).getByTestId("sns-open-detail").click();
    await page.getByTestId("sns-subscribe-queue").selectOption({ label: "cafe-orders-demo01" });
    await page.getByTestId("sns-subscribe-add").click();
    await expect(page.getByText("Successfully subscribed cafe-orders-demo01.")).toBeVisible();
    await page.getByTestId("sns-tab-publish").click();
    await page.getByTestId("sns-publish-message").fill('{"alert": "latte order waiting"}');
    await page.getByTestId("sns-publish").click();
    await expect(page.getByText("Message published. Delivery to subscribed queues is immediate in the sandbox.")).toBeVisible();
    await shot(page, "34-sns-console");

    // Prove delivery on the queue.
    await page.getByTestId("svc-sqs").click();
    await page.getByTestId("sqs-row").filter({ hasText: "cafe-orders-demo01" }).getByTestId("sqs-open-detail").click();
    await page.getByTestId("sqs-poll").click();
    await expect(page.getByTestId("sqs-message").first()).toContainText("latte");

    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
    await page.getByTestId("submit-lab").click();
    await page.getByTestId("confirm-action").click();
    await page.waitForURL(/\/results\//, { timeout: 120_000 });
    await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  });

  test("Mission 13: restore the deleted subscription", async ({ page }) => {
    test.setTimeout(600_000);
    await signIn(page, "demo-student2@cloudlabs.demo");
    await startLab(page, "Mission 13");

    // The topic exists with no subscription: subscribe the queue again.
    await page.getByTestId("svc-sns").click();
    await page.getByTestId("sns-row").filter({ hasText: "cafe-alerts-demo02" }).getByTestId("sns-open-detail").click();
    await expect(page.getByTestId("sns-subscription-count")).toHaveText("0");
    await page.getByTestId("sns-subscribe-queue").selectOption({ label: "cafe-orders-demo02" });
    await page.getByTestId("sns-subscribe-add").click();
    await expect(page.getByTestId("sns-subscription-row")).toContainText("cafe-orders-demo02");

    // Publish a test alert and prove it arrives on the queue.
    await page.getByTestId("sns-tab-publish").click();
    await page.getByTestId("sns-publish-message").fill('{"alert": "latte order is waiting"}');
    await page.getByTestId("sns-publish").click();
    await expect(page.getByText("Message published. Delivery to subscribed queues is immediate in the sandbox.")).toBeVisible();
    await shot(page, "35-sns-breakfix");
    await page.getByTestId("svc-sqs").click();
    await page.getByTestId("sqs-row").filter({ hasText: "cafe-orders-demo02" }).getByTestId("sqs-open-detail").click();
    await page.getByTestId("sqs-poll").click();
    await expect(page.getByTestId("sqs-message").first()).toContainText("latte");

    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
    await page.getByTestId("submit-lab").click();
    await page.getByTestId("confirm-action").click();
    await page.waitForURL(/\/results\//, { timeout: 120_000 });
    await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  });
});

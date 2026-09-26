import { execSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

// DynamoDB journey through the real UI on the platform default engine:
// AWS-style Create table (customize → on-demand) in the GUI → put-item in the CLI → GUI shows it →
// Create item in the GUI → progress → submit → 100 → sandbox cleaned up.

const PASSWORD = "cloudlabs-demo";
const TABLE = "cafe-demo02-orders";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 3 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 60_000 });
}

async function createItem(page: Page, attrs: [string, "String" | "Number", string][], key: string) {
  await page.getByTestId("create-item").click();
  await page.getByLabel("Value of orderId").fill(key);
  for (const [name, type, value] of attrs) {
    await page.getByTestId("add-attribute").click();
    await page.getByLabel("Attribute name").last().fill(name);
    await page.getByLabel(`Type of ${name}`).selectOption({ label: type });
    await page.getByLabel(`Value of ${name}`).fill(value);
  }
  await page.getByTestId("save-item").click();
  await expect(page.getByText("The item has been saved successfully.")).toBeVisible();
}

test("student completes the DynamoDB lab with console and CLI", async ({ page }) => {
  await signIn(page, "demo-student2@cloudlabs.demo");
  await page.getByTestId("lab-card").filter({ hasText: "Mission 2" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  const sessionId = new URL(page.url()).searchParams.get("session")!;
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  // The console opens on the lab's service; S3 is still available, unbuilt services are labelled.
  await expect(page.getByRole("heading", { name: "DynamoDB", exact: true })).toBeVisible();
  await expect(page.getByTestId("svc-s3")).toBeEnabled();
  await expect(page.getByTestId("svc-lambda")).toBeEnabled();

  // 1) GUI: Create table → Customize settings → On-demand
  await page.getByTestId("open-create-table").click();
  await page.getByTestId("new-table-name").fill(TABLE);
  await page.getByTestId("partition-key").fill("orderId");
  await page.getByTestId("customize-settings").check();
  await page.getByTestId("mode-on-demand").check();
  await expect(page.getByText("Not available in CloudLabs simulator").first()).toBeVisible();
  await page.getByTestId("create-table").click();
  await expect(page.getByText(`The ${TABLE} table was created successfully.`)).toBeVisible();
  await expect(page.getByRole("cell", { name: "On-demand" })).toBeVisible();
  await page.screenshot({ path: "../../docs/screenshots/08-dynamodb-tables.png" });

  // 2) CLI: put the first order (typed JSON), proving CLI and GUI share state
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, `aws dynamodb put-item --table-name ${TABLE} --item '{"orderId":{"S":"1001"},"drink":{"S":"latte"},"quantity":{"N":"2"}}' && echo PUT_$((40+2))`, "PUT_42");

  // 3) GUI: the CLI item is visible; add two more items in the GUI
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByRole("button", { name: TABLE }).click();
  await page.getByTestId("explore-items").click();
  await expect(page.getByTestId("item-row")).toHaveCount(1);
  await expect(page.getByTestId("item-row").first()).toContainText("latte");
  await createItem(page, [["drink", "String", "mocha"], ["quantity", "Number", "1"]], "1002");
  await createItem(page, [["drink", "String", "tea"], ["quantity", "Number", "3"]], "1003");
  await expect(page.getByTestId("item-row")).toHaveCount(3);
  await page.screenshot({ path: "../../docs/screenshots/09-dynamodb-items.png" });

  // 4) Progress → 100, submit → stored 100, cleanup
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 120_000 });
  await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  await expect.poll(() => execSync(`docker ps -a -q --filter label=cloudlabs.session=${sessionId}`, { encoding: "utf-8" }).trim(),
    { timeout: 90_000, intervals: [1000] }).toBe("");
});

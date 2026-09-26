import { execSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

// Lambda journey (MiniStack engine): create the function in the GUI → write the code in the GUI editor
// and Deploy → configure env/timeout/memory from the CLI → Test in the GUI → 100 → cleanup.

const FN = "cafe-demo01-orders";
const CODE = `import os


def lambda_handler(event, context):
    rate = float(os.environ["TAX_RATE"])
    subtotal = sum(i["price"] * i["qty"] for i in event.get("items", []))
    return {"total": round(subtotal * (1 + rate), 2)}
`;

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 90_000 });
}

test("student builds and tests a serverless checkout function", async ({ page }) => {
  test.setTimeout(420_000);
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-student1@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("lab-card").filter({ hasText: "Mission 5" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  const sessionId = new URL(page.url()).searchParams.get("session")!;
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  // Only Lambda runs in this lab's training cloud
  await expect(page.getByTestId("svc-lambda")).toBeEnabled();
  await expect(page.getByTestId("svc-s3")).toBeDisabled();

  // 1) GUI: create function (Author from scratch, Python 3.12, new execution role)
  await page.getByTestId("open-create-function").click();
  await expect(page.getByText("Not available in CloudLabs simulator").first()).toBeVisible();
  await page.getByTestId("function-name").fill(FN);
  await page.getByTestId("create-function").click();
  await expect(page.getByText(`Successfully created the function ${FN}.`)).toBeVisible({ timeout: 30_000 });

  // 2) GUI: write the code and Deploy
  await page.getByTestId("code-editor").fill(CODE);
  await expect(page.getByTestId("undeployed")).toBeVisible();
  await page.getByTestId("deploy").click();
  await expect(page.getByText(`Successfully updated the function ${FN}.`)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("undeployed")).toHaveCount(0);

  // 3) CLI: configuration
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, `aws lambda update-function-configuration --function-name ${FN} --timeout 10 --memory-size 256 --environment "Variables={TAX_RATE=0.08}" >/dev/null && echo CFG_$((40+2))`, "CFG_42");

  // 4) GUI: the Configuration tab shows it; Test with the example order
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByTestId("lambda-tab-config").click();
  await expect(page.getByTestId("memory")).toHaveValue("256");
  await expect(page.getByTestId("env-key")).toHaveValue("TAX_RATE");
  await page.getByTestId("lambda-tab-test").click();
  await page.getByTestId("test-event").fill('{"items": [{"price": 3, "qty": 2}, {"price": 4.5, "qty": 1}]}');
  await page.getByTestId("run-test").click();
  await expect(page.getByTestId("test-result")).toContainText("Executing function: succeeded", { timeout: 90_000 });
  await expect(page.getByTestId("test-result")).toContainText('"total": 11.34');
  await page.screenshot({ path: "../../docs/screenshots/12-lambda-test.png" });

  // 5) Progress (invokes the function during evidence capture) → submit → 100 → cleanup
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100", { timeout: 120_000 });
  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 180_000 });
  await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  await expect.poll(() => execSync(`docker ps -a -q --filter label=cloudlabs.session=${sessionId}`, { encoding: "utf-8" }).trim(),
    { timeout: 90_000, intervals: [1000] }).toBe("");
});

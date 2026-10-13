import { expect, type Page, test } from "@playwright/test";

// Mission 14 (Lambda + SQS + DynamoDB, MiniStack engine): table and queue from the CLI → function built
// in the Lambda console → Test with the SQS event template (the bad record is reported, not fatal) →
// SQS trigger added on the Triggers tab → an order sent from the SQS console is saved by the triggered
// function → progress (whose probe sends its own order through the pipeline) → submit → 100.

const TABLE = "cafe-demo03-orders";
const QUEUE = "cafe-demo03-incoming";
const FN = "cafe-demo03-worker";
const CODE = `import json
import os

import boto3

DB = boto3.client("dynamodb")


def lambda_handler(event, context):
    failures = []
    for record in event["Records"]:
        try:
            order = json.loads(record["body"])
            total = round(sum(i["price"] * i["qty"] for i in order.get("items", [])) * 1.08, 2)
            DB.put_item(TableName=os.environ["TABLE_NAME"],
                        Item={"orderId": {"S": str(order["orderId"])}, "total": {"N": str(total)}})
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
`;

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 90_000 });
}

test("student wires an SQS-triggered order pipeline and scores 100", async ({ page }) => {
  test.setTimeout(600_000);
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-student3@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("lab-card").filter({ hasText: "Mission 14" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  // 1) CLI: the table and the queue (their consoles are covered by their own specs)
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, `aws dynamodb create-table --table-name ${TABLE} --billing-mode PAY_PER_REQUEST --attribute-definitions AttributeName=orderId,AttributeType=S --key-schema AttributeName=orderId,KeyType=HASH >/dev/null && aws sqs create-queue --queue-name ${QUEUE} --attributes VisibilityTimeout=60 >/dev/null && echo BUILT_$((40+2))`, "BUILT_42");

  // 2) GUI: create the function, deploy the batch handler, configure it
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByTestId("svc-lambda").click();
  await page.getByTestId("open-create-function").click();
  await page.getByTestId("function-name").fill(FN);
  await page.getByTestId("create-function").click();
  await expect(page.getByText(`Successfully created the function ${FN}.`)).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("code-editor").fill(CODE);
  await page.getByTestId("deploy").click();
  await expect(page.getByText(`Successfully updated the function ${FN}.`)).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("lambda-tab-config").click();
  await page.getByTestId("timeout").fill("10");
  await page.getByTestId("add-env").click();
  await page.getByTestId("env-key").fill("TABLE_NAME");
  await page.getByTestId("env-value").fill(TABLE);
  await page.getByTestId("save-config").click();
  await expect(page.getByText(`Successfully updated the function ${FN}.`)).toBeVisible({ timeout: 30_000 });

  // 3) GUI: Test with the SQS template — one good order, one bad record reported in batchItemFailures
  await page.getByTestId("lambda-tab-test").click();
  await page.getByTestId("event-template").selectOption("sqs");
  await expect(page.getByTestId("test-event")).toHaveValue(/"messageId": "msg-2"/);
  await page.getByTestId("run-test").click();
  await expect(page.getByTestId("test-result")).toContainText("Executing function: succeeded", { timeout: 90_000 });
  await expect(page.getByTestId("test-result")).toContainText('"itemIdentifier": "msg-2"');

  // 4) GUI: add the SQS trigger
  await page.getByTestId("lambda-tab-triggers").click();
  await expect(page.getByText("There are no triggers.")).toBeVisible();
  await page.getByTestId("open-add-trigger").click();
  await expect(page.getByTestId("trigger-queue")).toHaveValue(QUEUE);
  await page.getByTestId("trigger-batch").fill("5");
  await page.getByTestId("trigger-report").check();
  await page.getByTestId("add-trigger-submit").click();
  await expect(page.getByText(`The trigger ${QUEUE} was successfully added to the function.`)).toBeVisible({ timeout: 30_000 });
  const row = page.getByTestId("trigger-row").filter({ hasText: QUEUE });
  await expect(row).toContainText("5");
  await expect(row.getByTestId("trigger-state")).toHaveText("Enabled");
  await page.screenshot({ path: "../../docs/screenshots/37-lambda-trigger.png" });

  // 5) GUI: send an order from the SQS console; CLI: the triggered function saved it
  await page.getByTestId("svc-sqs").click();
  await page.getByTestId("sqs-row").filter({ hasText: QUEUE }).getByTestId("sqs-open-detail").click();
  await page.getByTestId("sqs-tab-send").click();
  await page.getByTestId("sqs-message-body").fill('{"orderId": "1201", "items": [{"price": 4, "qty": 2}]}');
  await page.getByTestId("sqs-send").click();
  await expect(page.getByText("Message sent.")).toBeVisible();
  await page.getByTestId("tab-terminal").click();
  await termRun(page, `for i in $(seq 30); do T=$(aws dynamodb get-item --table-name ${TABLE} --key '{"orderId":{"S":"1201"}}' --query Item.total.N --output text); [ "$T" != "None" ] && break; sleep 1; done; echo "SAVED_$T"`, "SAVED_8.64");

  // 6) Progress (the probe sends its own order through the pipeline) → submit → 100
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100", { timeout: 180_000 });
  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 240_000 });
  await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
});

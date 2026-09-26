import { execSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

// EC2 journey: key pair in the GUI → security group via the CLI → Launch instance wizard in the GUI →
// an extra CLI instance breaks the cost check → terminate it in the GUI → 100 → cleanup.

const ID = "demo01";
const SG = `cafe-web-sg-${ID}`, KEY = `cafe-key-${ID}`, INSTANCE = `cafe-web-${ID}`;

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 60_000 });
}

test("student launches a web server with a least-privilege security group", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-student1@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("lab-card").filter({ hasText: "Mission 4" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  const sessionId = new URL(page.url()).searchParams.get("session")!;
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  // 1) GUI: key pair (private key shown once)
  await page.getByTestId("ec2-keys").click();
  await page.getByTestId("new-key-name").fill(KEY);
  await page.getByTestId("create-key").click();
  await expect(page.getByText("This is the only time you can save the private key file.")).toBeVisible();

  // 2) CLI: security group with HTTP from anywhere and SSH from campus only; plus an extra instance
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, `SG=$(aws ec2 create-security-group --group-name ${SG} --description web --query GroupId --output text) && aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null && aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 22 --cidr 10.20.0.0/16 >/dev/null && echo SG_$((40+2))`, "SG_42");
  await termRun(page, `AMI=$(aws ec2 describe-images --owners amazon --query "Images[0].ImageId" --output text) && aws ec2 run-instances --image-id $AMI --instance-type t2.micro --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=test-box}]" >/dev/null && echo RUN_$((40+2))`, "RUN_42");

  // 3) GUI: Launch instance wizard
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByTestId("ec2-instances").click();
  await page.getByTestId("open-launch").click();
  await page.getByTestId("instance-name").fill(INSTANCE);
  await page.getByText("Add additional tags").click();
  await page.getByTestId("add-tag").click();
  await page.getByLabel("Tag key").fill("Project");
  await page.getByLabel("Tag value").fill("cloudcafe");
  await page.getByTestId("instance-type").selectOption("t3.micro");
  await page.getByTestId("key-select").selectOption(KEY);
  await page.getByTestId("sg-existing").check();
  await page.getByLabel(`Security group ${SG}`).check();
  await expect(page.getByText("Not available in CloudLabs simulator").first()).toBeVisible();
  await page.getByTestId("launch-instance").click();
  await expect(page.getByText(`Successfully initiated launch of instance ${INSTANCE}.`)).toBeVisible();
  await expect(page.getByTestId("instance-row")).toHaveCount(2);
  await page.screenshot({ path: "../../docs/screenshots/11-ec2-instances.png" });

  // 4) Two running instances → cost task fails
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("90.00 / 100");
  await expect(page.getByTestId("task-cost")).toContainText("keep at most 1");

  // 5) GUI: terminate the extra instance → 100
  await page.getByLabel("Select test-box").check();
  await page.getByTestId("instance-state-menu").click();
  page.once("dialog", (d) => void d.accept());
  await page.getByTestId("terminate-instance").click();
  await expect(page.getByTestId("instance-row").filter({ hasText: "test-box" })).toContainText("Terminated");
  await page.waitForTimeout(10_500);
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");

  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 120_000 });
  await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  await expect.poll(() => execSync(`docker ps -a -q --filter label=cloudlabs.session=${sessionId}`, { encoding: "utf-8" }).trim(),
    { timeout: 90_000, intervals: [1000] }).toBe("");
});

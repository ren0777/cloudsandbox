import { expect, type Page, test } from "@playwright/test";

// Mission 15 (VPC + EC2, default engine): the network from the CLI → Create security group in the custom
// VPC → Launch instance with Network settings pointed at the public subnet → the Architecture tab draws the
// instance in its subnet → 100.

const VPC = "cafe-vpc-demo02";
const SUBNET = "cafe-public-demo02";
const SG = "cafe-web-sg-demo02";
const INSTANCE = "cafe-web-demo02";

async function termRun(page: Page, cmd: string, expectText: string | RegExp) {
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type(cmd, { delay: 2 });
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText(expectText, { timeout: 120_000 });
}

test("student launches the web server into its own public subnet and scores 100", async ({ page }) => {
  test.setTimeout(600_000);
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo-student2@cloudlabs.demo");
  await page.getByLabel("Password").fill("cloudlabs-demo");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("lab-card").filter({ hasText: "Mission 15" }).click();
  await page.getByTestId("start-lab").click();
  await page.waitForURL(/\/play\?session=/);
  await expect(page.getByTestId("session-state")).toHaveText("Running", { timeout: 120_000 });

  // 1) CLI: VPC, public subnet, internet gateway, route table + association (the VPC console has its own spec)
  await page.getByTestId("tab-terminal").click();
  await expect(page.getByText("Connected")).toBeVisible({ timeout: 30_000 });
  await termRun(page, [
    `V=$(aws ec2 create-vpc --cidr-block 10.0.0.0/16 --query Vpc.VpcId --output text)`,
    `aws ec2 create-tags --resources $V --tags Key=Name,Value=${VPC}`,
    `S=$(aws ec2 create-subnet --vpc-id $V --cidr-block 10.0.1.0/24 --query Subnet.SubnetId --output text)`,
    `aws ec2 create-tags --resources $S --tags Key=Name,Value=${SUBNET}`,
    `aws ec2 modify-subnet-attribute --subnet-id $S --map-public-ip-on-launch`,
    `G=$(aws ec2 create-internet-gateway --query InternetGateway.InternetGatewayId --output text)`,
    `aws ec2 create-tags --resources $G --tags Key=Name,Value=cafe-igw-demo02`,
    `aws ec2 attach-internet-gateway --internet-gateway-id $G --vpc-id $V`,
    `R=$(aws ec2 create-route-table --vpc-id $V --query RouteTable.RouteTableId --output text)`,
    `aws ec2 create-tags --resources $R --tags Key=Name,Value=cafe-public-rtb-demo02`,
    `aws ec2 create-route --route-table-id $R --destination-cidr-block 0.0.0.0/0 --gateway-id $G >/dev/null`,
    `aws ec2 associate-route-table --route-table-id $R --subnet-id $S >/dev/null`,
    `echo NET_$((40+2))`].join(" && "), "NET_42");

  // 2) GUI: the security group goes in the custom VPC
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByTestId("svc-ec2").click();
  await page.getByTestId("ec2-sgs").click();
  await page.getByTestId("open-create-sg").click();
  await page.getByTestId("new-sg-name").fill(SG);
  const sgVpc = page.getByTestId("new-sg-vpc").locator("option", { hasText: VPC });
  await page.getByTestId("new-sg-vpc").selectOption(await sgVpc.getAttribute("value") ?? "");
  await page.getByTestId("add-rule").click();
  await page.getByLabel("Rule type").selectOption("HTTP");
  await page.getByLabel("Source CIDR").fill("0.0.0.0/0");
  await page.getByTestId("create-sg").click();
  await expect(page.getByText(`Security group ${SG} created.`)).toBeVisible({ timeout: 30_000 });

  // 3) GUI: Launch instance → Network settings → the custom VPC and its public subnet
  await page.getByTestId("ec2-instances").click();
  await page.getByTestId("open-launch").click();
  await page.getByTestId("instance-name").fill(INSTANCE);
  await page.getByTestId("instance-type").selectOption("t3.micro");
  const vpcOption = page.getByTestId("launch-vpc").locator("option", { hasText: VPC });
  await page.getByTestId("launch-vpc").selectOption(await vpcOption.getAttribute("value") ?? "");
  await expect(page.getByTestId("launch-subnet").locator("option:checked")).toContainText(SUBNET);
  await expect(page.getByTestId("launch-public-ip")).toContainText("Enable");
  await page.getByTestId("sg-existing").check();
  await page.getByLabel(`Security group ${SG}`).check();
  await page.screenshot({ path: "../../docs/screenshots/38-launch-in-subnet.png" });
  await page.getByTestId("launch-instance").click();
  await expect(page.getByText(`Successfully initiated launch of instance ${INSTANCE}.`)).toBeVisible({ timeout: 60_000 });

  // 4) Architecture: the instance sits in the public subnet
  await page.getByRole("tab", { name: "Architecture" }).click();
  await expect(page.locator(`[data-node="vpc:subnet:${SUBNET}"]`)).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(`[data-testid="arch-node"][data-node^="ec2:instance:"]`)).toHaveCount(1);

  // 5) Progress → submit → 100
  await page.getByRole("tab", { name: "Console" }).click();
  await page.getByTestId("check-progress").click();
  await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100", { timeout: 120_000 });
  await page.getByTestId("submit-lab").click();
  await page.getByTestId("confirm-action").click();
  await page.waitForURL(/\/results\//, { timeout: 180_000 });
  await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
});

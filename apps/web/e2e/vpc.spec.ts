import { expect, type Page, test } from "@playwright/test";

// M44 VPC: Mission 8 is built end-to-end in the VPC console (VPC → subnet → internet gateway → route
// table/route/association → security group) and Mission 9's broken network is repaired the same way.
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

test.describe.serial("VPC labs in the console", () => {
  test("Mission 8: build CloudCafé's public network and score 100", async ({ page }) => {
    test.setTimeout(600_000);
    await signIn(page, "demo-student1@cloudlabs.demo");
    await startLab(page, "Mission 8");

    // Your VPCs: the VPC console is the initial service of a vpc lab.
    await expect(page.getByTestId("vpc-tab-vpcs")).toBeVisible();
    await page.getByTestId("vpc-open-create").click();
    await page.getByTestId("vpc-name").fill("cafe-vpc-demo01");
    await page.getByTestId("vpc-cidr").fill("10.0.0.0/16");
    await page.getByTestId("vpc-create-save").click();
    await expect(page.getByText("Successfully created VPC cafe-vpc-demo01.")).toBeVisible();
    await expect(page.getByTestId("vpc-row").filter({ hasText: "cafe-vpc-demo01" })).toBeVisible();

    // Subnets: public (auto-assign public IPv4 is on by default in the dialog).
    await page.getByTestId("vpc-tab-subnets").click();
    await page.getByTestId("subnet-open-create").click();
    await page.getByTestId("subnet-vpc-select").selectOption({ label: "cafe-vpc-demo01 (10.0.0.0/16)" });
    await page.getByTestId("subnet-name").fill("cafe-public-demo01");
    await page.getByTestId("subnet-cidr").fill("10.0.1.0/24");
    await expect(page.getByTestId("subnet-public")).toBeChecked();
    await page.getByTestId("subnet-create-save").click();
    await expect(page.getByText("Successfully created subnet cafe-public-demo01.")).toBeVisible();

    // Internet gateways: create, then attach to the VPC.
    await page.getByTestId("vpc-tab-igws").click();
    await page.getByTestId("igw-open-create").click();
    await page.getByTestId("igw-name").fill("cafe-igw-demo01");
    await page.getByTestId("igw-create-save").click();
    const igwRow = page.getByTestId("igw-row").filter({ hasText: "cafe-igw-demo01" });
    await igwRow.getByTestId("igw-attach-vpc").selectOption({ label: "cafe-vpc-demo01" });
    await igwRow.getByTestId("igw-attach").click();
    await expect(igwRow).toContainText("Attached");

    // Route tables: create, add the 0.0.0.0/0 route to the gateway, associate the subnet.
    await page.getByTestId("vpc-tab-rtbs").click();
    await page.getByTestId("rtb-open-create").click();
    await page.getByTestId("rtb-name").fill("cafe-public-rtb-demo01");
    await page.getByTestId("rtb-create-save").click();
    await page.getByTestId("rtb-row").filter({ hasText: "cafe-public-rtb-demo01" }).getByTestId("rtb-open-detail").click();
    const rtb = page.getByTestId("rtb-detail");
    await rtb.getByTestId("rtb-route-igw").selectOption({ label: "cafe-igw-demo01" });
    await rtb.getByTestId("rtb-route-add").click();
    await expect(rtb.getByRole("cell", { name: "0.0.0.0/0", exact: true })).toBeVisible();
    await expect(rtb.getByRole("cell", { name: "igw:cafe-igw-demo01", exact: true })).toBeVisible();
    await rtb.getByTestId("rtb-associate-subnet").selectOption({ label: "cafe-public-demo01 (10.0.1.0/24)" });
    await rtb.getByTestId("rtb-associate-add").click();
    await expect(rtb).toContainText("cafe-public-demo01");

    // Security groups: create in the VPC and allow HTTP from anywhere.
    await page.getByTestId("vpc-tab-sgs").click();
    await page.getByTestId("sg-open-create").click();
    await page.getByTestId("sg-name").fill("cafe-web-sg-demo01");
    await page.getByTestId("sg-create-save").click();
    await page.getByTestId("sg-row").filter({ hasText: "cafe-web-sg-demo01" }).getByTestId("sg-open-detail").click();
    const sg = page.getByTestId("sg-detail");
    await sg.getByTestId("sg-ingress-rule-add").click();  // defaults to TCP 80 from 0.0.0.0/0
    await sg.getByTestId("sg-save-rules").click();
    await expect(page.getByText("Successfully saved the security group rules.")).toBeVisible();
    // the banner shows before the list reloads: capture only once the row reports the saved rule
    const sgRow = page.getByTestId("sg-row").filter({ hasText: "cafe-web-sg-demo01" });
    await expect(sgRow.locator("td").nth(3)).toHaveText("1");  // inbound rules column
    await shot(page, "30-vpc-console");

    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
    await page.getByTestId("submit-lab").click();
    await page.getByTestId("confirm-action").click();
    await page.waitForURL(/\/results\//, { timeout: 120_000 });
    await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  });

  test("Mission 9: repair the broken public network", async ({ page }) => {
    test.setTimeout(900_000);  // the typed break-action setup builds a whole network (AWS CLI sequence)
    await signIn(page, "demo-student2@cloudlabs.demo");
    await startLab(page, "Mission 9", 300_000);

    // The route table lost its 0.0.0.0/0 route: put it back.
    await page.getByTestId("vpc-tab-rtbs").click();
    await page.getByTestId("rtb-row").filter({ hasText: "cafe-public-rtb-demo02" }).getByTestId("rtb-open-detail").click();
    const rtb = page.getByTestId("rtb-detail");
    await expect(rtb).not.toContainText("0.0.0.0/0");
    await rtb.getByTestId("rtb-route-igw").selectOption({ label: "cafe-igw-demo02" });
    await rtb.getByTestId("rtb-route-add").click();
    await expect(rtb).toContainText("0.0.0.0/0");

    // The security group lost its HTTP rule: add it back (SSH stays restricted to the VPC network).
    await page.getByTestId("vpc-tab-sgs").click();
    await page.getByTestId("sg-row").filter({ hasText: "cafe-web-sg-demo02" }).getByTestId("sg-open-detail").click();
    const sg = page.getByTestId("sg-detail");
    await sg.getByTestId("sg-ingress-rule-add").click();
    await sg.getByTestId("sg-save-rules").click();
    await expect(page.getByText("Successfully saved the security group rules.")).toBeVisible();
    await shot(page, "31-vpc-breakfix");

    await page.getByTestId("check-progress").click();
    await expect(page.getByTestId("progress-score")).toHaveText("100.00 / 100");
    await page.getByTestId("submit-lab").click();
    await page.getByTestId("confirm-action").click();
    await page.waitForURL(/\/results\//, { timeout: 120_000 });
    await expect(page.getByTestId("final-score")).toHaveText("100.00 / 100");
  });
});

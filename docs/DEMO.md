# Stackora — teacher demonstration script

A reproducible 10-minute core demo (Stackora v0.1.0): a student completes an S3 lab using **both** the web
console and the real AWS CLI, is graded on the **actual state** of their sandbox, and the instructor inspects
the evidence. The optional sections after it show the other services, instructor and admin tools, the learning
layer and multi-server readiness. Every section is automated in `apps/web/e2e/` (`journey.spec.ts` for §1–7,
`dynamodb`, `iam`, `ec2`, `lambda`, `instructor-roster`, `instructor-ops`, `architecture`, `breakfix-fun`,
`admin-courses` and `fleet` for the optional parts).

## 0. Prepare (once, ~5 minutes on first run)

Requirements: Docker Desktop (Windows with WSL2, or macOS) or Docker Engine with Compose v2 on Linux; see the
README prerequisites.

```powershell
scripts\up.ps1          # or: ./scripts/up.sh   — builds images, starts the stack, waits for health
scripts\demo-reset.ps1  # or: ./scripts/demo-reset.sh
```

`demo-reset` must end with `RESULT: READY`. It wipes previous demo data and demo sandboxes, reseeds the
accounts below and the course *Cloud Computing Demo*, imports the seven lab packs (Missions 1–7) and checks the
database, runner and sandbox images.

| Role | Email | Password |
|---|---|---|
| Student | `demo-student1@cloudlabs.demo` | `cloudlabs-demo` |
| Instructor | `demo-instructor@cloudlabs.demo` | `cloudlabs-demo` |
| Admin | `demo-admin@cloudlabs.demo` | `cloudlabs-demo` |

Open **http://localhost:3000**. While `CL_DEMO_MODE=true` the login page lists these accounts (with the
password) and signs you in with one click. Run `demo-reset` again before every presentation.

## 1. Student starts the lab
1. Sign in as **demo-student1**. *My labs* shows "Mission 1: CloudCafé goes online".
2. Open it: the briefing names the student's **personal bucket** `cafe-demo01-site` (each student gets a
   different name, so nobody can copy another's work).
3. Click **Start lab**. The setup steps show while the runner creates an isolated sandbox: a private
   network with no internet, an AWS emulator and a terminal. It takes under 10 s.
   - *Show the audience:* `docker ps --filter label=cloudlabs.session` lists this student's containers.

## 2. Create in the GUI → prove in the CLI
1. In **Console → S3 → General purpose buckets**, choose **Create bucket**. Point out the AWS-style form
   (AWS Region, Object Ownership, Block Public Access, Bucket Versioning, Tags) and the settings labelled
   *Not available in Stackora simulator*. Enter `cafe-demo01-site`, keep the defaults and choose **Create bucket**.
2. Switch to **AWS CLI** and run:
   ```bash
   aws s3 ls
   ```
   The bucket created in the GUI is listed. Both paths change the same simulated AWS state.

## 3. Change from the CLI → prove in the GUI
```bash
aws s3api put-bucket-versioning --bucket cafe-demo01-site --versioning-configuration Status=Enabled
echo '<h1>CloudCafe</h1>' > index.html && aws s3 cp index.html s3://cafe-demo01-site/
```
Back in **Console**: click **Refresh**, open the bucket. `index.html` is under *Objects*, and
*Properties → Bucket Versioning* shows **Enabled**.

## 4. Grading fails on purpose
Click **Check progress** (this doesn't use an attempt). The checklist ticks three tasks green and shows
**75.00 / 100**. The tag task fails with the exact reason: *"Bucket cafe-demo01-site should have tag
project=cloudcafe"*. The grader looked at real state, not at which buttons were clicked.

## 5. Fix it → 100
1. Console → bucket → **Properties → Tags → Edit** → *Add tag* `project` = `cloudcafe` → **Save changes**.
2. Wait 10 s (progress checks are rate-limited), then **Check progress**: **100.00 / 100**.
3. **Submit for grading → Submit**. The sandbox is locked (terminal closes with "Lab submitted"),
   an evidence snapshot is captured and graded, and the result page shows **100.00 / 100**.

## 6. Instructor evidence
1. Sign out, sign in as **demo-instructor** → *Courses* → the assignment.
2. The results table shows *Sam Student 100.00*, attempts used, and an *Export CSV* button.
3. Click the attempt pill `#1: 100.00`. For every check you see **expected vs actual**, marks, the
   hidden check, the grade history (with **Regrade from stored evidence**), the session timeline
   (REQUESTED → … → TERMINATED) and the **sha256 of the immutable graded snapshot** (*Show raw evidence*).
4. Optional: **Reopen…** on a student grants an extra attempt or a new deadline. The reason and your
   name are recorded permanently.

## 7. Cleanup
```bash
docker ps -a --filter label=cloudlabs.session      # empty: containers removed after submit
docker network ls --filter label=cloudlabs.session # empty: the private network is gone too
```
Optionally sign in as **demo-admin** → *Runtime*: runner health, seats in use (0/4),
provisioning p50/p95 and failures in the last 24 h.

## Optional: Mission 2 (DynamoDB, about 5 minutes)
Sign in as **demo-student2** and open *Mission 2: CloudCafé takes orders*. In **DynamoDB → Tables → Create
table**, enter `cafe-demo02-orders` with partition key `orderId`, choose **Customize settings → On-demand**, then
create it. In **AWS CLI**, run
`aws dynamodb put-item --table-name cafe-demo02-orders --item '{"orderId":{"S":"1001"},"drink":{"S":"latte"},"quantity":{"N":"2"}}'`.
In the console, choose **Explore table items** to see the CLI item, then **Create item** twice more. **Check progress** shows
100. Point out the hidden check: storing the quantity as a String instead of a Number loses the task.

## Optional: Mission 3 (IAM least privilege, about 5 minutes)
Sign in as **demo-student3** and open *Mission 3*. In **IAM → User groups**, create `baristas-demo03`. In
**Policies → Create policy**, write a JSON policy allowing only `s3:GetObject` on
`arn:aws:s3:::cafe-demo03-site/*` and name it `menu-read-demo03`. Attach it to the group with **Add
permissions**. In **AWS CLI**, create the user and add it to the group:
`aws iam create-user --user-name barista-demo03 && aws iam add-user-to-group --group-name baristas-demo03 --user-name barista-demo03`.
Show the **Policy simulator** (labelled *Simulated by Stackora*): GetObject **Allowed**, DeleteObject
**Denied**. Then try attaching `AmazonS3ReadOnlyAccess` instead and watch the least-privilege task fail on the
payroll-bucket check.

## Optional: Mission 4 (EC2 web server, about 6 minutes)
Sign in as **demo-student1**, open *Mission 4*, and in **EC2 → Key Pairs** create `cafe-key-demo01` (the
private key is shown only once). In **AWS CLI**, create security group `cafe-web-sg-demo01` with HTTP from
`0.0.0.0/0` and SSH from `10.20.0.0/16` only. Then use **Instances → Launch instances**: name
`cafe-web-demo01`, type **t3.micro**, the key pair, **Select existing security group**, and tag
`Project=cloudcafe`. Point out the warning the wizard shows if SSH is open to 0.0.0.0/0 (the hidden check), and
that launching a second instance costs the "exactly one instance running" task until it's terminated.

## Optional: Mission 5 (Lambda checkout, about 6 minutes)
Sign in as **demo-student1** and open *Mission 5*. Only **Lambda** is enabled in the nav, because this lab runs on
the engine that can execute code. **Create function** `cafe-demo01-orders` (Author from scratch, Python 3.12).
On the **Code** tab, write a handler that sums `price × qty` over `event["items"]` and adds tax from
`TAX_RATE`, then **Deploy**. In **AWS CLI** run `aws lambda update-function-configuration --function-name
cafe-demo01-orders --timeout 10 --memory-size 256 --environment "Variables={TAX_RATE=0.08}"`. Back in the
console, **Test** with `{"items": [{"price": 3, "qty": 2}, {"price": 4.5, "qty": 1}]}`. It returns
`{"total": 11.34}`. Each run takes about 10 seconds. **Check progress** invokes the function itself, including
a hidden empty-order test.

## Optional: Instructor setup (course, roster, assignment, about 4 minutes)
1. Sign in as **demo-instructor** → **New course** (e.g. `CS-341`, *Cloud Computing*) → open it.
2. **Import roster**: paste
   `email,name` / `asha@cloudlabs.demo,Asha Patel` / `not-an-email,Broken` / `asha@cloudlabs.demo,Asha Again`
   (one row per line) and choose **Preview**. Point out the row-level errors (invalid email, *duplicate of row 2*)
   and that nothing has been imported. Remove the two bad lines and **Preview** again, then choose **Import**.
3. The temporary password is shown **once** (**Download credentials CSV**). The roster shows *Awaiting first
   sign-in*.
4. **New assignment** → choose a lab, dates and attempts → **Create assignment**.
5. In a private window, sign in as `asha@cloudlabs.demo` with the temporary password: Stackora requires a new
   password before anything else, then shows the lab.
6. Every one of these actions is in the audit log (see *Admin* below).

## Optional: Live monitoring, gradebook and audit (about 5 minutes)
1. Sign in as **demo-student3** in a private window, start *Mission 1*, create the bucket
   (`aws s3 mb s3://cafe-demo03-site`) and choose **Check progress**.
2. As **demo-instructor**, on the course card choose **Live**. Leo's row shows the task strip and score from his
   last progress check, time left and last activity. Point out that watching never touches his sandbox.
3. **Extend** → 15 minutes, reason "network outage". Then **End lab** → *Grade it now*, reason "class ended".
   Leo's window moves to his result: *Ended by instructor*. If he hadn't changed anything, no attempt is used.
4. **Gradebook**: one row per student and one column per lab, colour-coded by percentage, with *late*
   and regrade marks. Select Leo's score to open the per-check evidence (expected vs actual, snapshot sha256).
   **Export CSV** has name, email, student ID, course, assignment, lab, score, max, percentage,
   attempts used/allowed, late, submitted time and status.
5. Sign in as **demo-admin**:
   - **Runtime** shows engine images per runner (floci default, moto, ministack) and every running lab, with
     *+15 min* and *End* buttons.
   - **Users**: search, change a role, deactivate, reset a password (a temporary password is shown once).
   - **Course staff**: add or remove instructors.
   - **Audit log**: every action above in plain language, with the reason, actor and request ID. Entries can't
     be edited or deleted. Instructors see the same log for their course under **Activity log**.

## Optional: Learning layer (break-fix, architecture, cost, badges, about 6 minutes)
1. As **demo-instructor**, open the course and set **Class leaderboard** to *On, with anonymous nicknames*.
2. As **demo-student1**, open *Mission 6: The baristas are admins (break-fix)*. The card and the player say it
   starts broken. Open **Architecture**: the baristas group and AdministratorAccess carry a warning flag, and
   the intern has an inline policy. The **Simulated · educational** cost meter says IAM itself is free.
3. Repair it in the console or CLI: detach AdministratorAccess, attach `orders-rw-demo01` to the group, then
   remove and delete the intern. Watch the diagram update without reloading. **Check progress** shows 100.
4. **Submit**: the result page shows new badges (*Incident responder*, *Right first time*, …) and *What you built*.
5. **My labs** shows level, XP and badges. The leaderboard shows *You* and everyone else under nicknames.
6. Optional cost lesson: in Mission 4, launch a second instance and watch the meter; stop it and point out
   that the root volume is still charged.

## Optional: Multi-server readiness (about 4 minutes)
1. Start the second runner: `docker compose -f infra/docker-compose.yml --profile multi up -d runner2`, then register it
   as **demo-admin** in **Runtime → Register runner** (`runner-local-2`, `http://runner2:7070`, secret
   `dev-runner2-secret-change-me`). Stackora contacts it before saving, so a wrong secret or id is refused.
2. The Runtime page shows both runners: health, seats, CPU and memory, and engine images. runner-local-2 runs in
   **gateway** mode, exactly as a runner on another server would.
3. Start labs as two students: they land on different runners (least loaded first). Both terminals and consoles work.
4. **Drain** runner-local-2. A new lab goes to runner-local-1, while the running one continues. At zero it says
   *Drained: safe to stop*.
5. Talking point: if a server dies, its labs are ended honestly after 5 minutes (`runner_lost`, no attempt used),
   never silently recreated elsewhere, and cleaned up when it returns.

## Optional: Instructor Lab Builder (about 6 minutes)
1. As **demo-instructor**, nav **Labs**: *My drafts*, *My labs*, *Shared labs* and *Built-in missions*.
   Point out that a built-in mission (e.g. Mission 1) offers **Clone** and **Export**. Choose **New lab**
   to show the template gallery (S3 basics, DynamoDB basics, IAM least privilege, EC2 web server, Lambda,
   IAM break-fix) — a working lab, not a blank page.
2. **Clone** Mission 1 (or start from the S3 basics template). The draft opens on Overview with a green
   validation panel; the Tasks tab shows the checks as generated forms, and **Preview** shows the student
   view (no checks, no private files).
3. Change the first task title, **Save**, then open **YAML** to show the same change. Return to **Test &
   publish** and choose **Run test**: it runs untouched (0), partial (50) and solution (100) in real sandboxes
   on moto and floci. *Publish* stays disabled until the run passes.
4. **Publish**: the lab becomes an immutable version private to the author. **Share** it so every instructor
   can assign or clone it (each action is in the audit log).
5. Assign the new lab to the demo course and start it as a student — the changed task is what they see.

## Talking points
- **Safe and free:** no AWS account. Each student's cloud is an isolated AWS emulator (Floci, about 34 MB per
  student) in Docker, with CPU, memory, PID and time limits, and no internet access.
- **Transferable skills:** the console follows AWS terminology and workflows, and the terminal is the real
  AWS CLI with standard syntax.
- **Fair grading:** per-student resource names, grading of real state, the same evidence always
  produces the same score, and evidence can't be edited (database triggers).
- **Honest simulator:** unsupported features are labelled in the console (e.g. *Static website
  hosting: Not available in Stackora simulator*) and rejected when a lab is imported.

## If something goes wrong
| Symptom | Fix |
|---|---|
| `demo-reset` prints `NOT READY` for images | `docker compose -f infra/docker-compose.yml --profile images build` |
| "All lab seats are in use" | another session is running; `demo-reset` clears demo sandboxes |
| Terminal shows "Reconnecting…" | wait a few seconds; the session page still works through the console |
| Page shows an error with `ref: …` | `docker compose -f infra/docker-compose.yml logs api \| findstr <ref>` |

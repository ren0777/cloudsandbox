"""Demo Mode (PLAN §16) — developer/presentation tooling, not student product scope.

    python -m app.demo reset

Refuses to run unless CL_DEMO_MODE=true. Destroys the demo environment's sandboxes (through the runner),
wipes and reseeds the demo rows, imports the S3 lab pack, checks runtime health and prints a summary.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta

from sqlalchemy import select, text

from .auth.routes import create_user
from .config import get_settings
from .db import sessionmaker
from .labs.importer import import_package
from .labs.package import load_pack
from .maintenance import wipe_demo
from .models import Assignment, Course, CourseStaff, Enrolment, LabSession, Role, Runner, SessionState, User
from .runtime.runner_client import RunnerError, client_for, get_runner
from .sessions import state as st

DEMO_PASSWORD = "cloudlabs-demo"
DEMO_DOMAIN = "cloudlabs.demo"
DEMO_LABS = [("s3-basics", "Mission 1: CloudCafé goes online"),
             ("dynamodb-basics", "Mission 2: CloudCafé takes orders"),
             ("iam-least-privilege", "Mission 3: Least privilege for the baristas"),
             ("ec2-web-server", "Mission 4: A web server for CloudCafé"),
             ("lambda-basics", "Mission 5: CloudCafé's serverless checkout"),
             ("iam-breakfix", "Mission 6: The baristas are admins (break-fix)"),
             ("lambda-dynamodb", "Mission 7: CloudCafé's serverless orders"),
             ("vpc-basics", "Mission 8: CloudCafé's public network"),
             ("vpc-breakfix", "Mission 9: The café's website went dark (break-fix)"),
             ("sqs-basics", "Mission 10: CloudCafé's order queue"),
             ("sqs-breakfix", "Mission 11: The orders queue is stuck (break-fix)"),
             ("sns-basics", "Mission 12: CloudCafé's order alerts"),
             ("sns-breakfix", "Mission 13: The alerts stopped (break-fix)")]
DEMO_USERS = [
    ("demo-admin", "Dana Admin", Role.admin, "dadmin"),
    ("demo-instructor", "Dr. Ira Instructor", Role.instructor, "dinstr"),
    ("demo-student1", "Sam Student", Role.student, "demo01"),
    ("demo-student2", "Priya Student", Role.student, "demo02"),
    ("demo-student3", "Leo Student", Role.student, "demo03"),
]


async def reset() -> int:
    s = get_settings()
    if not s.demo_mode:
        print("REFUSED: demo reset needs CL_DEMO_MODE=true")
        return 2
    runner = get_runner()
    ok = True

    # 1. Sandboxes: demo users' live sessions (on whichever runner holds them), plus every sandbox of this env
    #    on every registered runner when it is the demo env.
    destroyed = 0
    async with sessionmaker()() as db:
        live = (await db.execute(select(LabSession.id, LabSession.runner_id).join(User, User.id == LabSession.user_id).where(
            User.is_demo, LabSession.state.notin_([SessionState.TERMINATED, SessionState.FAILED])))).all()
        runners = list((await db.scalars(select(Runner).where(Runner.status != "retired"))).all())
    targets: dict[str, set[str]] = {}
    for sid, rid in live:
        targets.setdefault(rid, set()).add(str(sid))
    for r in runners:
        client = client_for(r)
        try:
            if s.env == "demo":
                targets.setdefault(r.id, set()).update(sb["sandbox_id"] for sb in await client.list_sandboxes(env=s.env))
            for sid in sorted(targets.get(r.id, ())):
                await client.destroy_sandbox(sid)
                destroyed += 1
        except RunnerError as e:
            print(f"  ! runner {r.id}: {e.message}")
            ok = ok and r.id != s.runner_id  # only the platform's own runner is required for the demo

    # 2. Wipe + reseed demo rows.
    counts = await wipe_demo()
    async with sessionmaker()() as db:
        users = {}
        for local, name, role, short in DEMO_USERS:
            users[local] = await create_user(db, f"{local}@{DEMO_DOMAIN}", name, role, DEMO_PASSWORD,
                                             short_id=short, is_demo=True)
        course = Course(code="CLOUD-DEMO", title="Cloud Computing Demo", is_demo=True)
        db.add(course)
        await db.flush()
        db.add(CourseStaff(course_id=course.id, user_id=users["demo-instructor"].id))
        for k in ("demo-student1", "demo-student2", "demo-student3"):
            db.add(Enrolment(course_id=course.id, user_id=users[k].id))
        now = st.now()
        imported = []
        for i, (slug, title) in enumerate(DEMO_LABS):
            lv, created = await import_package(db, load_pack(f"{s.labs_dir}/{slug}"))
            imported.append((slug, lv.version, created))
            db.add(Assignment(course_id=course.id, lab_version_id=lv.id, title=title,
                              open_at=now - timedelta(hours=1), due_at=now + timedelta(days=7 + i),
                              close_at=now + timedelta(days=8 + i), allow_late=True, max_attempts=3,
                              grade_policy="best", created_by=users["demo-instructor"].id))
        await db.commit()
        db_ok = (await db.execute(text("SELECT 1"))).scalar() == 1

    # 3. Health.
    try:
        cap = await runner.capacity()
        runner_ok, images_ok = bool(cap["docker_ok"]), bool(cap.get("images_ok"))
        seats = f"{cap['active']}/{cap['max_sandboxes']} sandboxes on host"
    except RunnerError as e:
        runner_ok = images_ok = False
        seats = e.message
    ok &= db_ok and runner_ok and images_ok

    def mark(v: bool) -> str:
        return "OK  " if v else "FAIL"

    print("Stackora demo reset")
    print(f"  sandboxes destroyed : {destroyed}")
    print(f"  demo rows removed   : {sum(counts.values())}")
    for slug, version, created in imported:
        print(f"  lab pack {slug:<16}: {'imported' if created else 'already present'} (v{version})")
    print(f"  [{mark(db_ok)}] database")
    print(f"  [{mark(runner_ok)}] runner ({seats})")
    print(f"  [{mark(images_ok)}] sandbox images (emulator + terminal)")
    print("  Sign in at http://localhost:3000 with password", DEMO_PASSWORD)
    for local, name, role, _ in DEMO_USERS:
        print(f"    {role.value:<10} {local + '@' + DEMO_DOMAIN:<32} {name}")
    print("RESULT:", "READY" if ok else "NOT READY")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] != ["reset"]:
        print("usage: python -m app.demo reset")
        sys.exit(2)
    sys.exit(asyncio.run(reset()))

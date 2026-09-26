"""Phase 8 — Instructor Lab Builder backend (docs/NEXT.md milestone 36): check catalogue, drafts CRUD and
ownership, row-level validation, YAML round-trip, clone / import / export, student preview, lab
visibility and sharing."""

from __future__ import annotations

import io
import tarfile
from datetime import timedelta

import yaml
from sqlalchemy import select, update

from app.db import sessionmaker
from app.labs import drafts as dr
from app.labs.importer import import_package
from app.labs.package import load_pack, pack_from_files
from app.models import AuditEvent, Lab, LabDraft
from app.sessions import state as st
from tests.conftest import LABS, login

B = "/api/instructor/builder"


async def audits(action: str) -> list[AuditEvent]:
    async with sessionmaker()() as db:
        return list((await db.scalars(select(AuditEvent).where(AuditEvent.action == action)
                                      .order_by(AuditEvent.id))).all())


async def new_draft(c, **body) -> dict:
    r = await c.post(f"{B}/drafts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def authored_lab(owner_id, lab_dir: str = "dynamodb-basics"):
    """A lab published by an instructor (publishing itself is milestone 37)."""
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(f"{LABS}/{lab_dir}"), owner_id=owner_id)
        await db.commit()
        return lv


def assignment_body(course_id, lab_version_id) -> dict:
    now = st.now()
    return {"course_id": str(course_id), "lab_version_id": str(lab_version_id), "title": "Week 3",
            "open_at": now.isoformat(), "due_at": (now + timedelta(days=3)).isoformat(),
            "close_at": (now + timedelta(days=4)).isoformat()}


# ------------------------------------------------------------------------------ check catalogue
async def test_check_types_expose_generated_param_schemas(world):
    c = await login(world.instructor)
    r = await c.get(f"{B}/check-types")
    assert r.status_code == 200, r.text
    body = r.json()
    types = {t["type"]: t for t in body["check_types"]}
    b = types["s3.bucket_exists"]
    assert b["service"] == "s3" and "bucket" in b["params_schema"]["properties"]
    assert "bucket" in b["params_schema"]["required"] and b["reads"]
    assert set(b["engines"]) == {"moto", "floci", "ministack"} and b["engines"]["floci"]["usable"]
    assert {"hidden", "weight", "feedback"} <= set(body["common_fields"]["properties"])
    assert "type" not in body["common_fields"]["properties"]
    assert "s3" in body["services"] and body["engines"]["primary"] == ["moto", "floci"]
    assert body["editable_files"] == list(dr.EDITABLE_FILES)
    stu = await login(world.alice)
    assert (await stu.get(f"{B}/check-types")).status_code == 403


# --------------------------------------------------------------------------- drafts + ownership
async def test_blank_draft_crud_and_ownership(world):
    c = await login(world.instructor)
    d = await new_draft(c, source="blank", title="My first lab")
    assert d["status"] == "draft" and d["title"] == "My first lab"
    assert d["slug"] == f"new-lab-{world.instructor.short_id}"
    assert d["validation"]["ok"], d["validation"]
    assert d["validation"]["content_sha256"]
    assert "private/solution.sh" in d["content"]["files"] and d["read_only_files"] == []
    url = f"{B}/drafts/{d['id']}"
    # a second blank draft gets its own id
    assert (await new_draft(c))["slug"] == f"new-lab-{world.instructor.short_id}-2"

    other = await login(world.other_instructor)
    assert (await other.get(url)).status_code == 404
    assert (await other.put(url, json={"lab": d["content"]["lab"]})).status_code == 404
    assert (await other.get(f"{url}/yaml")).status_code == 404
    assert (await other.post(f"{url}/validate")).status_code == 404
    assert (await other.get(f"{url}/preview")).status_code == 404
    assert (await other.delete(url)).status_code == 404
    assert (await other.get(f"{B}/drafts")).json()["drafts"] == []
    stu = await login(world.alice)
    assert (await stu.get(url)).status_code == 403
    admin = await login(world.admin)
    assert (await admin.get(url)).status_code == 200
    assert len((await admin.get(f"{B}/drafts")).json()["drafts"]) == 2

    listed = (await c.get(f"{B}/drafts")).json()["drafts"]
    assert {x["id"] for x in listed} >= {d["id"]} and "content" not in listed[0]
    lab = d["content"]["lab"] | {"title": "Renamed lab"}
    r = await c.put(url, json={"lab": lab, "files": {"private/notes.md": "grading notes"}})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed lab" and r.json()["content"]["files"]["private/notes.md"] == "grading notes"
    assert (await c.delete(url)).status_code == 204
    assert (await c.get(url)).status_code == 404
    evs = await audits("lab.draft_created")
    assert len(evs) == 2 and evs[0].details["source"] == "blank" and evs[0].actor_id == world.instructor.id


async def test_validation_errors_are_row_level_and_invalid_drafts_still_save(world):
    c = await login(world.instructor)
    d = await new_draft(c)
    url = f"{B}/drafts/{d['id']}"
    lab = d["content"]["lab"]
    lab["tasks"][0]["checks"] = [{"type": "s3.bucket_exists"}, {"type": "s3.nope", "bucket": "x"}]
    lab["tasks"].append({"id": "second", "title": "Second task", "checks": [{"type": "s3.bucket_exists", "bucket": "b"}]})
    r = await c.put(url, json={"lab": lab})
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert not v["ok"] and v["content_sha256"] is None
    # schema error (marks missing on the second task) points at the task by id
    assert any(e["task"] == "second" and e["field"] == "marks" for e in v["errors"]), v["errors"]
    assert r.json()["content"]["lab"]["tasks"][1]["id"] == "second"  # saved even though invalid

    del lab["tasks"][1]
    r = await c.put(url, json={"lab": lab})
    errs = r.json()["validation"]["errors"]
    assert {(e["task"], e["check"], e["field"]) for e in errs} >= {("create-bucket", 1, "bucket"),
                                                                  ("create-bucket", 2, None)}, errs
    assert any("unknown check type" in e["message"] for e in errs)

    lab["tasks"][0]["checks"] = [{"type": "s3.bucket_exists", "bucket": "{{ bucket }}"}]
    r = await c.put(url, json={"lab": lab, "files": {"private/expected.yaml": "empty: 0\nsolution: 50\n",
                                                     "private/partial.sh": "aws s3 mb s3://x\n"}})
    msgs = [e["message"] for e in r.json()["validation"]["errors"]]
    assert any("full marks (100)" in m for m in msgs) and any("partial: give the score" in m for m in msgs), msgs
    assert all(e["loc"] == "private/expected.yaml" for e in r.json()["validation"]["errors"])

    r = await c.put(url, json={"files": {"private/expected.yaml": "x: &a [1]\nempty: *a\n"}})
    assert any("aliases" in e["message"] for e in r.json()["validation"]["errors"])
    r = await c.put(url, json={"files": {"private/expected.yaml": "empty: 0\npartial: 40\nsolution: 100\n"}})
    assert r.json()["validation"]["ok"], r.json()["validation"]
    # removing the solution blocks testing
    r = await c.put(url, json={"files": {"private/solution.sh": ""}})
    assert "private/solution.sh" not in r.json()["content"]["files"]
    assert any(e["loc"] == "private/solution.sh" for e in r.json()["validation"]["errors"])
    # explicit validate gives the same result and stores it
    r = await c.post(f"{url}/validate")
    assert r.status_code == 200 and not r.json()["ok"]
    assert (await c.get(url)).json()["validation"]["errors"] == r.json()["errors"]
    # files outside the editable set are refused and nothing is saved
    r = await c.put(url, json={"files": {"public/setup.sh": "echo hi"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "lab_invalid"
    assert "public/setup.sh" not in (await c.get(url)).json()["content"]["files"]


async def test_editing_resets_a_test_result_and_published_drafts_are_read_only(world):
    c = await login(world.instructor)
    d = await new_draft(c)
    url = f"{B}/drafts/{d['id']}"
    async with sessionmaker()() as db:
        await db.execute(update(LabDraft).where(LabDraft.id == d["id"]).values(status="passed"))
        await db.commit()
    assert (await c.put(url, json={"lab": d["content"]["lab"]})).json()["status"] == "passed"  # no change
    lab = d["content"]["lab"] | {"title": "Changed"}
    assert (await c.put(url, json={"lab": lab})).json()["status"] == "draft"
    for status, code in (("published", "draft_published"), ("testing", "draft_testing")):
        async with sessionmaker()() as db:
            await db.execute(update(LabDraft).where(LabDraft.id == d["id"]).values(status=status))
            await db.commit()
        r = await c.put(url, json={"lab": lab | {"title": "Again"}})
        assert r.status_code == 409 and r.json()["error"]["code"] == code
        r = await c.put(f"{url}/yaml", json={"yaml": "schema_version: 1\n"})
        assert r.status_code == 409
    assert (await c.delete(url)).status_code == 409  # still testing


# -------------------------------------------------------------------------------------- YAML
async def test_yaml_round_trip(world):
    c = await login(world.instructor)
    d = await new_draft(c, source="clone", lab_version_id=str(world.lab_version.id))
    url = f"{B}/drafts/{d['id']}"
    text = (await c.get(f"{url}/yaml")).json()["yaml"]
    assert yaml.safe_load(text) == d["content"]["lab"]
    assert "story: |" in text  # multi-line text stays readable
    r = await c.put(f"{url}/yaml", json={"yaml": text.replace("duration_minutes: 45", "duration_minutes: 50")})
    assert r.status_code == 200, r.text
    assert r.json()["content"]["lab"]["duration_minutes"] == 50 and r.json()["validation"]["ok"]
    assert yaml.safe_load(r.json()["yaml"]) == r.json()["content"]["lab"]
    # the same lab through the form and through YAML gives the same content hash
    same = await c.put(url, json={"lab": r.json()["content"]["lab"]})
    assert same.json()["validation"]["content_sha256"] == r.json()["validation"]["content_sha256"]
    for bad, msg in (("tasks: [unclosed", "not valid YAML"), ("- a list", "must be a mapping"),
                     ("schema_version: 1\nwhen: 2024-01-01\n", "quote dates"),
                     ("a: &a [x, x, x, x, x, x, x, x, x]\nb: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]\n"
                      "c: [*b, *b, *b, *b, *b, *b, *b, *b, *b]\n", "aliases")):
        r = await c.put(f"{url}/yaml", json={"yaml": bad})
        assert r.status_code == 422, r.text
        assert msg in r.json()["error"]["errors"][0]["message"]
    assert (await c.get(url)).json()["content"]["lab"]["duration_minutes"] == 50  # nothing saved
    # schema-invalid YAML is saved like a form edit, with its errors
    r = await c.put(f"{url}/yaml", json={"yaml": "schema_version: 1\nid: x\n"})
    assert r.status_code == 200 and not r.json()["validation"]["ok"]


# --------------------------------------------------------------------- clone / preview / export
async def test_clone_builtin_mission_gets_a_new_id_and_keeps_private_files(world):
    c = await login(world.instructor)
    d = await new_draft(c, source="clone", lab_version_id=str(world.lab_version.id))
    lab = d["content"]["lab"]
    assert lab["id"] == d["slug"] == f"s3-basics-{world.instructor.short_id}"
    assert lab["version"] == "1.0.0" and lab["title"].endswith("(copy)")
    assert d["base_lab_version_id"] == str(world.lab_version.id)
    assert set(d["content"]["files"]) == {"private/solution.sh", "private/partial.sh", "private/expected.yaml",
                                          "private/notes.md"}
    assert d["validation"]["ok"], d["validation"]
    original = load_pack(f"{LABS}/s3-basics")
    assert yaml.safe_load(original.yaml_text) | {"id": lab["id"], "version": "1.0.0", "title": lab["title"]} == lab
    # a clone of a clone gets yet another id
    assert (await new_draft(c, source="clone", lab_version_id=str(world.lab_version.id)))["slug"] \
        == f"s3-basics-{world.instructor.short_id}-2"
    assert (await c.post(f"{B}/drafts", json={"source": "clone"})).status_code == 400


async def test_clone_break_fix_keeps_setup_script_read_only(world):
    lv = None
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(f"{LABS}/iam-breakfix"))
        await db.commit()
    c = await login(world.instructor)
    d = await new_draft(c, source="clone", lab_version_id=str(lv.id))
    assert d["read_only_files"] and all(f.startswith("public/") for f in d["read_only_files"])
    assert d["validation"]["ok"], d["validation"]
    ro = d["read_only_files"][0]
    r = await c.put(f"{B}/drafts/{d['id']}", json={"files": {ro: "echo changed\n"}})
    assert r.status_code == 422 and "read-only" in r.json()["error"]["errors"][0]["message"]
    # sending a read-only file back unchanged is fine (the UI may post every file)
    r = await c.put(f"{B}/drafts/{d['id']}", json={"files": {ro: d["content"]["files"][ro]}})
    assert r.status_code == 200


async def test_preview_is_the_redacted_student_view(world):
    c = await login(world.instructor)
    d = await new_draft(c, source="clone", lab_version_id=str(world.lab_version.id))
    r = await c.get(f"{B}/drafts/{d['id']}/preview")
    assert r.status_code == 200, r.text
    view = r.json()["lab"]
    bucket = f"cafe-{world.instructor.short_id}-site"
    assert r.json()["variables"]["bucket"] == bucket and bucket in view["story"]
    assert [t["id"] for t in view["tasks"]] == [t["id"] for t in d["content"]["lab"]["tasks"]]
    assert "checks" not in view["tasks"][0]
    text = r.text
    for secret in ("s3.object_content_type", "s3.bucket_exists", "hidden"):
        assert secret not in text
    for f, body in d["content"]["files"].items():
        for line in body.splitlines():
            if len(line.strip()) > 12:
                assert line.strip() not in text, f"{f} leaked into the preview: {line!r}"
    # an invalid draft has no preview
    lab = d["content"]["lab"] | {"tasks": []}
    await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab})
    r = await c.get(f"{B}/drafts/{d['id']}/preview")
    assert r.status_code == 422 and r.json()["error"]["code"] == "lab_invalid"


async def test_export_and_import_round_trip(world):
    c = await login(world.instructor)
    r = await c.get(f"/api/instructor/lab-versions/{world.lab_version.id}/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/gzip"
    assert 'filename="s3-basics-1.2.0.tar.gz"' in r.headers["content-disposition"]
    data = r.content
    assert (await c.get(f"/api/instructor/lab-versions/{world.lab_version.id}/export")).content == data  # stable
    files = dr.from_targz(data)
    assert set(files) == {"lab.yaml", "private/solution.sh", "private/partial.sh", "private/expected.yaml",
                          "private/notes.md"}
    assert pack_from_files(files).content_sha256 == world.lab_version.content_sha256
    stu = await login(world.alice)
    assert (await stu.get(f"/api/instructor/lab-versions/{world.lab_version.id}/export")).status_code == 403

    r = await c.post(f"{B}/drafts/import", files={"file": ("s3-basics.tar.gz", data, "application/gzip")})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["slug"] == "s3-basics" and d["content"]["files"]["private/solution.sh"]
    # the id belongs to the built-in mission, so validation says to rename it
    errs = d["validation"]["errors"]
    assert [e["loc"] for e in errs] == ["id"] and "already used" in errs[0]["message"]
    lab = d["content"]["lab"] | {"id": "my-s3-lab"}
    assert (await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab})).json()["validation"]["ok"]
    assert (await audits("lab.draft_created"))[0].details["source"] == "import"


def _tar(entries: list[tuple[str, bytes | None]], gz: bool = True) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz" if gz else "w") as tf:
        for name, data in entries:
            ti = tarfile.TarInfo(name)
            if data is None:
                ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tf.addfile(ti)
            else:
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


async def test_import_rejects_unsafe_or_broken_packs(world):
    c = await login(world.instructor)
    lab_yaml = load_pack(f"{LABS}/s3-basics").yaml_text.encode()
    cases = {
        b"not a tarball": "not a .tar.gz",
        _tar([("lab.yaml", lab_yaml), ("private/link", None)]): "only regular files",
        _tar([("lab.yaml", lab_yaml), ("../escape.sh", b"x")]): "invalid path",
        _tar([("lab.yaml", lab_yaml), ("other/file.txt", b"x")]): "only lab.yaml, public/",
        _tar([("lab.yaml", lab_yaml), ("private/big.bin", b"x" * (257 * 1024))]): "larger than",
        _tar([("lab.yaml", lab_yaml), ("private/blob.bin", b"\xff\xfe\x00")]): "UTF-8",
        _tar([("private/solution.sh", b"x")]): "lab.yaml is missing",
        _tar([("lab.yaml", b"- just a list")]): "must be a mapping",
    }
    for data, msg in cases.items():
        r = await c.post(f"{B}/drafts/import", files={"file": ("pack.tar.gz", data)})
        assert r.status_code == 422, (msg, r.text)
        assert any(msg in e["message"] for e in r.json()["error"]["errors"]), (msg, r.json())
    # a plain .tar with lab.yaml inside one folder is fine, and a schema-invalid pack becomes a draft to fix
    r = await c.post(f"{B}/drafts/import", files={"file": ("p.tar", _tar([("pk/lab.yaml", b"schema_version: 1\n")],
                                                                         gz=False))})
    assert r.status_code == 201, r.text
    assert not r.json()["validation"]["ok"]
    async with sessionmaker()() as db:
        assert len((await db.scalars(select(LabDraft))).all()) == 1


# ------------------------------------------------------------------------ visibility + sharing
async def test_authored_labs_are_private_until_shared(world):
    lv = await authored_lab(world.instructor.id)
    owner, other, admin = await login(world.instructor), await login(world.other_instructor), await login(world.admin)

    def listed(r):
        return {x["id"]: x for x in r.json()["lab_versions"]}
    mine = listed(await owner.get("/api/instructor/lab-versions"))
    assert mine[str(lv.id)]["mine"] and not mine[str(lv.id)]["builtin"] and not mine[str(lv.id)]["shared"]
    assert mine[str(lv.id)]["owner"]["name"] == world.instructor.name
    assert mine[str(world.lab_version.id)]["builtin"] and mine[str(world.lab_version.id)]["owner"] is None
    assert str(lv.id) not in listed(await other.get("/api/instructor/lab-versions"))
    assert str(lv.id) in listed(await admin.get("/api/instructor/lab-versions"))

    # invisible → 404 for assign, clone and export
    assert (await other.post("/api/instructor/assignments",
                             json=assignment_body(world.other_course.id, lv.id))).status_code == 404
    assert (await other.post(f"{B}/drafts", json={"source": "clone", "lab_version_id": str(lv.id)})).status_code == 404
    assert (await other.get(f"/api/instructor/lab-versions/{lv.id}/export")).status_code == 404
    other_asg = (await other.post("/api/instructor/assignments",
                                  json=assignment_body(world.other_course.id, world.lab_version.id))).json()["id"]
    r = await other.patch(f"/api/instructor/assignments/{other_asg}", json={"lab_version_id": str(lv.id)})
    assert r.status_code == 404
    # the owner can assign it in their own course
    assert (await owner.post("/api/instructor/assignments",
                             json=assignment_body(world.course.id, lv.id))).status_code == 201

    async with sessionmaker()() as db:
        lab_id = (await db.get(Lab, lv.lab_id)).id
    share = f"/api/instructor/labs/{lab_id}/share"
    assert (await other.post(share, json={"shared": True})).status_code == 404
    assert (await (await login(world.alice)).post(share, json={"shared": True})).status_code == 403
    r = await owner.post(share, json={"shared": True})
    assert r.status_code == 200 and r.json()["shared"] is True
    assert (await owner.post(share, json={"shared": True})).status_code == 200  # no-op, not audited again
    assert listed(await other.get("/api/instructor/lab-versions"))[str(lv.id)]["shared"]
    assert (await other.post("/api/instructor/assignments",
                             json=assignment_body(world.other_course.id, lv.id))).status_code == 201
    d = await new_draft(other, source="clone", lab_version_id=str(lv.id))
    assert d["slug"] == f"dynamodb-basics-{world.other_instructor.short_id}"
    assert (await other.get(f"/api/instructor/lab-versions/{lv.id}/export")).status_code == 200
    # an admin can unshare an authored lab; built-in missions can't be (un)shared by anyone
    assert (await admin.post(share, json={"shared": False})).json()["shared"] is False
    async with sessionmaker()() as db:
        builtin_lab = world.lab_version.lab_id
    assert (await admin.post(f"/api/instructor/labs/{builtin_lab}/share", json={"shared": True})).status_code == 404
    assert str(lv.id) not in listed(await other.get("/api/instructor/lab-versions"))
    evs = await audits("lab.shared")
    assert [e.details["shared"] for e in evs] == [True, False]
    assert evs[0].actor_id == world.instructor.id and evs[1].actor_id == world.admin.id


async def test_cloning_your_own_lab_prepares_its_next_version(world):
    lv = await authored_lab(world.instructor.id)
    c = await login(world.instructor)
    d = await new_draft(c, source="clone", lab_version_id=str(lv.id))
    assert d["slug"] == "dynamodb-basics" and d["content"]["lab"]["version"] != lv.version
    assert d["content"]["lab"]["title"] == load_pack(f"{LABS}/dynamodb-basics").definition.title
    assert d["validation"]["ok"], d["validation"]
    major, minor, _ = map(int, lv.version.split("."))
    assert d["content"]["lab"]["version"] == f"{major}.{minor + 1}.0"
    # keeping the published version number is flagged before any test run
    lab = d["content"]["lab"] | {"version": lv.version}
    errs = (await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab})).json()["validation"]["errors"]
    assert [e["loc"] for e in errs] == ["version"] and "already published" in errs[0]["message"]


async def test_import_package_never_adds_a_version_to_someone_elses_lab(world):
    from app.errors import ApiError
    await authored_lab(world.instructor.id)
    pkg = load_pack(f"{LABS}/dynamodb-basics")
    for owner in (None, world.other_instructor.id):
        async with sessionmaker()() as db:
            try:
                await import_package(db, pkg, owner_id=owner)
                raise AssertionError("import into another owner's lab must fail")
            except ApiError as e:
                assert e.code == "lab_owner_conflict" and e.status == 409
    async with sessionmaker()() as db:  # nor can an author import over a built-in mission
        try:
            await import_package(db, load_pack(f"{LABS}/s3-basics"), owner_id=world.instructor.id)
            raise AssertionError("an author must not add versions to a built-in mission")
        except ApiError as e:
            assert e.code == "lab_owner_conflict"


async def test_demo_reset_removes_demo_authors_labs_and_drafts(world, monkeypatch):
    from app.auth.routes import create_user
    from app.config import get_settings
    from app.maintenance import wipe_demo
    from app.models import LabVersion, Role
    from tests.conftest import PASSWORD
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    async with sessionmaker()() as db:
        demo = await create_user(db, "demo-inst@x.edu", "Demo Instructor", Role.instructor, PASSWORD, is_demo=True)
        await db.commit()
    lv = await authored_lab(demo.id)
    dc = await login(demo)
    await new_draft(dc, source="clone", lab_version_id=str(lv.id))
    await dc.post(f"/api/instructor/labs/{lv.lab_id}/share", json={"shared": True})
    real = await new_draft(await login(world.instructor), source="clone", lab_version_id=str(lv.id))
    counts = await wipe_demo()
    assert counts["lab_drafts"] == 1 and counts["labs"] == 1 and counts["lab_versions"] == 1
    async with sessionmaker()() as db:
        assert await db.get(LabVersion, lv.id) is None
        kept = await db.get(LabDraft, real["id"])
        assert kept is not None and kept.base_lab_version_id is None  # the real author's clone survives
        assert await db.get(LabVersion, world.lab_version.id) is not None  # built-ins untouched

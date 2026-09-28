"""Phase 10, milestone 46 — Lab Builder autosave support on the server: a content revision (`rev`) on
every draft, optimistic concurrency on save, and the guarantees the autosave UI depends on.

The revision is a hash of the *content*, not of `updated_at`: a validate run, a test run or a status
change must never make an in-flight autosave look stale, while another tab saving different content must.
"""

from __future__ import annotations

from app.labs import drafts as dr
from tests.conftest import login
from tests.test_lab_builder import B, new_draft


def test_fingerprint_is_order_independent_and_content_sensitive():
    a = {"lab": {"id": "x", "tasks": []}, "files": {"private/notes.md": "n"}}
    b = {"files": {"private/notes.md": "n"}, "lab": {"tasks": [], "id": "x"}}
    assert dr.fingerprint(a) == dr.fingerprint(b)          # key order never matters (it comes from JSONB)
    c = {"lab": {"id": "x", "tasks": []}, "files": {"private/notes.md": "different"}}
    assert dr.fingerprint(c) != dr.fingerprint(a)
    # it works for content that is not a valid lab at all — a draft is allowed to hold work in progress
    assert len(dr.fingerprint({"lab": {}, "files": {}})) == 64
    assert dr.fingerprint({"lab": {}, "files": {}}) != dr.fingerprint({"lab": {"tasks": []}, "files": {}})


async def test_autosave_follows_the_revision_the_server_returns(world):
    c = await login(world.instructor)
    d = await new_draft(c, source="blank", title="Autosave")
    url = f"{B}/drafts/{d['id']}"
    assert isinstance(d["rev"], str) and len(d["rev"]) == 64
    # a run of debounced saves: each echoes the rev of the previous response, exactly as the UI does
    for i in range(3):
        r = await c.put(url, json={"lab": d["content"]["lab"] | {"title": f"Autosave {i}"},
                                   "base_rev": d["rev"]})
        assert r.status_code == 200, r.text
        assert r.json()["rev"] != d["rev"]      # content changed → the revision moves on
        d = r.json()
    assert (await c.get(url)).json()["content"]["lab"]["title"] == "Autosave 2"
    # the revision is exposed on the list view too, so a page can save straight after listing
    assert {(x["id"], x["rev"]) for x in (await c.get(f"{B}/drafts")).json()["drafts"]} >= {(d["id"], d["rev"])}


async def test_a_stale_autosave_is_refused_and_never_overwrites_newer_content(world):
    c = await login(world.instructor)
    d = await new_draft(c, source="blank", title="Two tabs")
    url = f"{B}/drafts/{d['id']}"
    lab, base = d["content"]["lab"], d["rev"]

    newer = (await c.put(url, json={"lab": lab | {"title": "tab B"}, "base_rev": base})).json()
    assert newer["content"]["lab"]["title"] == "tab B"

    stale = await c.put(url, json={"lab": lab | {"title": "tab A"}, "base_rev": base})
    assert stale.status_code == 409, stale.text
    err = stale.json()["error"]
    assert err["code"] == "stale_revision" and err["rev"] == newer["rev"]
    assert "reload" in err["message"]

    current = (await c.get(url)).json()
    assert current["content"]["lab"]["title"] == "tab B"          # tab A did not win
    assert current["rev"] == newer["rev"]


async def test_saving_without_a_revision_is_still_allowed(world):
    """Callers that have just re-read the draft (import, clone, the YAML flow before M46) omit `base_rev`
    and keep working — only a *wrong* revision is refused."""
    c = await login(world.instructor)
    d = await new_draft(c, source="blank")
    url = f"{B}/drafts/{d['id']}"
    r = await c.put(url, json={"lab": d["content"]["lab"] | {"title": "No rev sent"}})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "No rev sent"


async def test_a_validation_run_never_makes_an_autosave_look_stale(world):
    """`updated_at` moves on validate/test/status changes; the content revision must not, or a teacher
    would get a spurious "changed somewhere else" while simply working."""
    c = await login(world.instructor)
    d = await new_draft(c, source="blank", title="Stable")
    url = f"{B}/drafts/{d['id']}"
    assert (await c.post(f"{url}/validate")).status_code == 200
    r = await c.put(url, json={"lab": d["content"]["lab"] | {"title": "Still current"}, "base_rev": d["rev"]})
    assert r.status_code == 200, r.text
    assert r.json()["content"]["lab"]["title"] == "Still current"


async def test_re_saving_identical_content_keeps_the_revision(world):
    """A save that changes nothing must not move the revision — the client's next `base_rev` has to stay
    valid, or autosave would report "changed somewhere else" while the teacher does nothing.

    The first round trip can still normalize: an optional file stored as empty text (`private/notes.md`
    on a blank draft) is dropped by `apply_edit`, which is the same rule as clearing the field in the
    Scripts tab."""
    c = await login(world.instructor)
    d = await new_draft(c, source="blank")
    url = f"{B}/drafts/{d['id']}"

    def body(draft: dict) -> dict:
        editable = set(draft["editable_files"])
        return {"lab": draft["content"]["lab"],
                "files": {k: v for k, v in draft["content"]["files"].items() if k in editable},
                "base_rev": draft["rev"]}

    first = await c.put(url, json=body(d))
    assert first.status_code == 200, first.text
    normalized = first.json()

    again = await c.put(url, json=body(normalized))
    assert again.status_code == 200, again.text
    assert again.json()["rev"] == normalized["rev"]      # unchanged content, unchanged revision
    # …and the stale check keeps working: the rev the client holds is still accepted after the no-op
    third = await c.put(url, json=body(normalized))
    assert third.status_code == 200


async def test_invalid_partial_content_autosaves_and_is_still_protected(world):
    """Autosave must never refuse half-finished work, and must never let an older tab revive it."""
    c = await login(world.instructor)
    d = await new_draft(c, source="blank", title="Half done")
    url = f"{B}/drafts/{d['id']}"
    lab = d["content"]["lab"]
    lab["tasks"][0]["checks"] = [{"type": "s3.bucket_exists"}, {"type": "s3.nope", "bucket": "x"}]

    saved = await c.put(url, json={"lab": lab, "base_rev": d["rev"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["validation"]["ok"] is False              # saved, with row-level errors
    assert saved.json()["validation"]["errors"]

    older = await c.put(url, json={"lab": d["content"]["lab"], "base_rev": d["rev"]})
    assert older.status_code == 409                               # the incomplete save is not reverted
    assert (await c.get(url)).json()["content"]["lab"] == lab


async def test_yaml_apply_is_protected_by_the_same_revision(world):
    c = await login(world.instructor)
    d = await new_draft(c, source="blank", title="YAML")
    url = f"{B}/drafts/{d['id']}"
    lab, base = d["content"]["lab"], d["rev"]

    form = (await c.put(url, json={"lab": lab | {"title": "form wins"}, "base_rev": base})).json()

    stale = await c.put(f"{url}/yaml", json={"yaml": dr.lab_to_yaml(lab), "base_rev": base})
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "stale_revision"
    assert (await c.get(url)).json()["content"]["lab"]["title"] == "form wins"

    fresh = (await c.get(url)).json()
    ok = await c.put(f"{url}/yaml", json={"yaml": dr.lab_to_yaml(fresh["content"]["lab"] | {"title": "yaml wins"}),
                                          "base_rev": fresh["rev"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["content"]["lab"]["title"] == "yaml wins"
    assert ok.json()["rev"] != fresh["rev"]

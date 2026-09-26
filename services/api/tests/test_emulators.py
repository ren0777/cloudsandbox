"""EmulatorAdapter registry and engine-selection rules (no Docker)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from app.config import get_settings
from app.db import sessionmaker
from app.labs.package import load_pack
from app.labs.schema import LabValidationError
from app.models import LabSession
from app.runtime import emulators
from tests.conftest import LABS, login, wait_state


def test_every_engine_has_a_capability_file_and_same_interface():
    for name in emulators.ENGINES:
        a = emulators.get(name)
        assert a.capabilities.emulator == name
        assert callable(a.client)


def test_unknown_engine_rejected():
    with pytest.raises(emulators.UnknownEngine):
        emulators.get("localstack")


def test_default_resolution_and_candidates(monkeypatch):
    monkeypatch.setattr(get_settings(), "default_emulator", "floci")
    assert emulators.resolve("default") == "floci"
    assert emulators.resolve("moto") == "moto"
    assert emulators.candidates("default") == emulators.ENGINES  # must work on every engine
    assert emulators.candidates("moto") == ("moto",)


def test_default_lab_rejected_if_any_engine_lacks_an_operation(tmp_path, monkeypatch):
    """A 'default' lab must be valid on every engine, so flipping the default can't break it."""
    from app.runtime import capabilities
    real = capabilities.load

    def fake(name: str = "moto"):
        c = real(name)
        if name == "floci":
            c = c.model_copy(deep=True)
            c.services["s3"].pop("PutBucketTagging")
        return c

    monkeypatch.setattr(capabilities, "load", fake)
    with pytest.raises(LabValidationError) as e:
        load_pack(Path(LABS) / "s3-basics")
    assert "on floci" in str(e.value) and "s3:PutBucketTagging" in str(e.value)
    # the same lab pinned to moto is fine
    dst = tmp_path / "lab"
    shutil.copytree(Path(LABS) / "s3-basics", dst)
    data = yaml.safe_load((dst / "lab.yaml").read_text(encoding="utf-8"))
    data["runtime"] = {"emulator": "moto"}
    (dst / "lab.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert load_pack(dst).definition.runtime.emulator == "moto"


@pytest.mark.parametrize("engine", emulators.ENGINES)
async def test_session_records_and_requests_the_default_engine(world, fake_runner, monkeypatch, engine):
    monkeypatch.setattr(get_settings(), "default_emulator", engine)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    async with sessionmaker()() as db:
        assert (await db.get(LabSession, sid)).engine == engine
    assert fake_runner.sandboxes[sid]["engine"] == engine
    # engine names never reach the student
    body = (await c.get(f"/api/sessions/{sid}")).text + (await c.get(f"/api/console/services?session_id={sid}")).text
    assert "moto" not in body.lower() and "floci" not in body.lower()


async def test_console_services_scoped_to_own_session(world, fake_runner):
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    bob = await login(world.bob)
    assert (await bob.get(f"/api/console/services?session_id={sid}")).status_code == 404

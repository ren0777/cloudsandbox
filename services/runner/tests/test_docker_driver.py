"""Integration tests against the real Docker daemon (run inside the runner container)."""
import base64
import hashlib
import io
import tarfile
import uuid

import docker
import pytest

from app.config import Settings
from app.docker_driver import DockerDriver, DriverError, net_name
from app.driver import CreateSandbox, JobSpec, ResetSandbox

pytestmark = pytest.mark.docker
ENGINES = ["moto", "floci", "ministack"]  # every configured engine must pass the same sandbox guarantees
TEST_SECRET = "runner-pytest-secret-0123456789abcdef"  # >= 32 chars: config refuses dev-length secrets


def _bundle(files: dict[str, str]) -> JobSpec:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, content in files.items():
            data = content.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))
    raw = buf.getvalue()
    return JobSpec(bundle_b64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest(),
                   script="run.sh", timeout_s=60)


@pytest.fixture
def driver():
    d = DockerDriver(Settings(secret=TEST_SECRET, id="runner-pytest", max_sandboxes=2, reattach_interval_s=0))
    yield d
    for s in d.list(None):
        d.destroy(s.sandbox_id)


def _create(d, engine="moto", **kw):
    sid = str(uuid.uuid4())
    return d.create(CreateSandbox(sandbox_id=sid, env="rtest", engine=engine,
                                  terminal_credential="student:secretpass1", **kw))


@pytest.mark.parametrize("engine", ENGINES)
def test_create_status_job_reset_destroy(driver, engine):
    info = _create(driver, engine, setup=_bundle({"run.sh": "aws s3 mb s3://seeded-bucket\n"}))
    sid = info.sandbox_id
    port = {"moto": "5000", "floci": "4566", "ministack": "4566"}[engine]
    assert info.engine == engine
    assert info.emulator_endpoint.endswith(f":{port}") and info.terminal_endpoint.endswith(":7681/ws")
    st = driver.status(sid)
    assert st.exists and st.emulator.state == "running" and st.terminal.state == "running"

    client = docker.from_env()
    net = client.networks.get(net_name(sid))
    assert net.attrs["Internal"] is True
    emu = client.containers.get(f"cl-sbx-{sid}-emulator")
    hc = emu.attrs["HostConfig"]
    assert hc["ReadonlyRootfs"] and hc["PidsLimit"] == 128 and hc["Memory"] == 384 * 1024 * 1024
    assert hc["CapDrop"] == ["ALL"] and "no-new-privileges" in hc["SecurityOpt"]
    assert emu.attrs["Config"]["User"] == "10001"

    # Setup job ran against this sandbox's emulator; jobs see its state.
    res = driver.run_job(sid, _bundle({"run.sh": "aws s3 ls\n"}))
    assert res.exit_code == 0, res.output
    assert "seeded-bucket" in res.output

    # No internet egress from the sandbox.
    res = driver.run_job(sid, _bundle({"run.sh": "python3 -c \"import socket;socket.create_connection(('1.1.1.1',80),3)\"\n"}))
    assert res.exit_code != 0

    # Reset wipes emulator state (no setup this time) but keeps the sandbox.
    driver.reset(sid, ResetSandbox(terminal_credential="student:secretpass2"))
    assert emu.labels["cloudlabs.engine"] == engine and driver.status(sid).emulator.state == "running"
    res = driver.run_job(sid, _bundle({"run.sh": "aws s3 ls\n"}))
    assert res.exit_code == 0 and "seeded-bucket" not in res.output

    driver.destroy(sid)
    driver.destroy(sid)  # idempotent
    st = driver.status(sid)
    assert not st.exists and st.emulator.state == "missing"
    assert not client.containers.list(all=True, filters={"label": f"cloudlabs.session={sid}"})


@pytest.mark.parametrize("engine", ENGINES)
def test_sandboxes_are_isolated(driver, engine):
    a = _create(driver, engine)
    b = _create(driver, engine)
    emu_b_ip = b.emulator_endpoint.split("//")[1].split(":")[0]
    port = b.emulator_endpoint.rsplit(":", 1)[1]
    code = f"import socket;socket.create_connection(('{emu_b_ip}',{port}),3)"
    res = driver.run_job(a.sandbox_id, _bundle({"run.sh": f'python3 -c "{code}"\n'}))
    assert res.exit_code != 0, "sandbox A must not reach sandbox B's emulator"


def test_capacity_full(driver):
    _create(driver)
    _create(driver)
    with pytest.raises(DriverError) as e:
        _create(driver)
    assert e.value.code == "capacity_full"


def test_bad_bundle_rejected(driver):
    info = _create(driver)
    job = _bundle({"run.sh": "true\n"})
    job.sha256 = "0" * 64
    with pytest.raises(DriverError) as e:
        driver.run_job(info.sandbox_id, job)
    assert e.value.code == "bundle_hash_mismatch"


def test_unknown_engine_rejected(driver):
    with pytest.raises(DriverError) as e:
        _create(driver, "nope-engine")
    assert e.value.code == "unknown_emulator"


def test_capacity_reports_host_and_engines_and_stats_are_scoped(driver):
    cap = driver.capacity()
    assert cap.docker_ok and cap.cpu_count and cap.mem_total_mib and 0 < cap.mem_available_mib <= cap.mem_total_mib
    assert cap.engines.get("moto") is True  # emulator + terminal images present
    info = _create(driver)
    other = DockerDriver(Settings(secret=TEST_SECRET, id="runner-pytest-other", max_sandboxes=2, reattach_interval_s=0))
    st = driver.stats("rtest")
    assert [s.sandbox_id for s in st.sandboxes] == [info.sandbox_id]
    assert st.sandboxes[0].memory_mib > 0 and st.sandboxes[0].memory_limit_mib > 0
    assert st.sandbox_memory_mib == st.sandboxes[0].memory_mib
    assert other.stats("rtest").sandboxes == []  # another runner id never sees (or counts) these sandboxes
    assert other.list("rtest") == []


def test_reattach_never_blocks_destroy(driver):
    """Regression (phase 7 load test): the reattach loop re-attached control-plane containers to a network whose
    sandbox was being destroyed, so the network could never be removed ("has active endpoints")."""
    client = docker.from_env()
    cp = client.containers.run(driver.s.terminal_image, entrypoint=["sleep", "120"], detach=True,
                               labels={"cloudlabs.role": "control-plane", "cloudlabs.env": "rtest"})
    try:
        info = _create(driver)
        sid = info.sandbox_id
        net = client.networks.get(net_name(sid))
        net.reload()
        assert cp.id in net.attrs["Containers"]  # direct mode attaches the control plane
        for comp in ("terminal", "emulator"):  # a destroy that removed the containers but not the network yet
            driver._remove_container(driver._get_container(sid, comp))
        net.disconnect(cp, force=True)
        driver.reattach_all()  # must not re-attach the control plane to the half-destroyed sandbox
        net.reload()
        assert cp.id not in (net.attrs.get("Containers") or {})
        driver.destroy(sid)
        with pytest.raises(docker.errors.NotFound):
            client.networks.get(net_name(sid))
    finally:
        cp.remove(force=True)

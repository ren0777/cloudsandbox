"""Lab tester (PLAN Verification / §7b): proves a lab pack grades correctly on the REAL runtime.

    python -m app.labtest /labs/s3-basics [/labs/other ...]

For each scenario in private/expected.yaml (empty → 0, partial.sh → expected, solution.sh → 100 …):
fresh sandbox → run the private script in a one-off *job container* (never a student terminal) →
capture evidence → pure grade → compare → destroy. Exit code 0 only if every scenario matches.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import secrets
import shlex
import sys
import tarfile
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from collections.abc import Awaitable, Callable

import yaml

from .config import get_settings
from .grader import evidence as ev
from .grader.grade import collectors_for, grade, probes_for, to_json
from .labs.package import LabPackage, load_pack, setup_job, tar_members
from .labs.render import compute_variables
from .runtime import emulators
from .runtime.runner_client import RunnerClient, get_runner

LABTEST_SHORT_ID = "labtst"
SCRIPTS = {"partial": "partial.sh", "solution": "solution.sh"}
RESET = "reset"  # break-fix only: a Reset must reproduce the same broken baseline


@dataclass
class ScenarioResult:
    name: str
    expected: Decimal
    actual: Decimal | None
    detail: str = ""
    engine: str = ""
    result: dict | None = None  # the full grade result (per-task, per-check), for the Lab Builder

    @property
    def ok(self) -> bool:
        return self.actual is not None and self.actual == self.expected


def _job_bundle(pkg: LabPackage, script: str, variables: dict[str, str]) -> dict:
    files = tar_members(pkg.private_bundle)
    if script not in files:
        raise FileNotFoundError(f"private/{script} missing")
    exports = "".join(f"export {k.upper()}={shlex.quote(v)}\n" for k, v in variables.items())
    runner_script = f"#!/bin/bash\nset -euo pipefail\n{exports}bash {shlex.quote(script)}\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in {**files, "_labtest_run.sh": runner_script.encode()}.items():
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), 0o755 if name.endswith(".sh") else 0o644
            tf.addfile(ti, io.BytesIO(data))
    raw = buf.getvalue()
    return {"bundle_b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest(),
            "script": "_labtest_run.sh", "timeout_s": 120}


async def _score(runner: RunnerClient, pkg: LabPackage, engine: str, endpoint: str,
                 variables: dict[str, str]) -> dict:
    d = pkg.definition
    payload = await ev.capture(endpoint, collectors_for(d), engine, probes_for(d, variables))
    return grade(d, variables, payload)


async def run_scenario(runner: RunnerClient, pkg: LabPackage, name: str, expected: Decimal,
                       engine: str, sandbox_id: str | None = None) -> ScenarioResult:
    s = get_settings()
    d = pkg.definition
    variables = compute_variables(d, LABTEST_SHORT_ID)
    sid = sandbox_id or str(uuid.uuid4())
    req = {
        "sandbox_id": sid, "env": s.env, "engine": engine,
        "terminal_credential": f"labtest:{secrets.token_hex(12)}",
        "emulator": {"cpus": s.emulator_cpus, "memory_mib": s.emulator_memory_mib, "pids": s.emulator_pids},
        "terminal": {"cpus": s.terminal_cpus, "memory_mib": s.terminal_memory_mib, "pids": s.terminal_pids},
        "setup": setup_job(pkg.public_bundle, d, variables),
    }
    try:
        info = await runner.create_sandbox(req)
        detail = ""
        if name == RESET:
            first = await _score(runner, pkg, engine, info["emulator_endpoint"], variables)
            reset = {k: v for k, v in req.items() if k in ("emulator", "terminal", "terminal_credential", "setup")}
            info = await runner.reset_sandbox(sid, reset)
            second = await _score(runner, pkg, engine, info["emulator_endpoint"], variables)
            if first["score"] != second["score"]:
                return ScenarioResult(name, expected, None,
                                      f"reset changed the baseline: {first['score']} -> {second['score']}",
                                      engine, to_json(second))
            failed = [f"{t['task_id']}" for t in second["tasks"] if not t["passed"]]
            detail = f"reset reproduced the baseline; failed tasks: {', '.join(failed) or '-'}"
            return ScenarioResult(name, expected, second["score"], detail, engine, to_json(second))
        if name in SCRIPTS:
            res = await runner.run_job(sid, _job_bundle(pkg, SCRIPTS[name], variables))
            if res["exit_code"] != 0:
                return ScenarioResult(name, expected, None, f"{SCRIPTS[name]} exited {res['exit_code']}: "
                                                            f"{res['output'][-400:]}", engine)
        result = await _score(runner, pkg, engine, info["emulator_endpoint"], variables)
        failed = [f"{t['task_id']}" for t in result["tasks"] if not t["passed"]]
        detail = f"failed tasks: {', '.join(failed) or '-'}"
        return ScenarioResult(name, expected, result["score"], detail, engine, to_json(result))
    finally:
        try:
            await runner.destroy_sandbox(sid)
        except Exception:
            pass


def expected_scores(pkg: LabPackage) -> dict[str, Decimal]:
    exp_file = tar_members(pkg.private_bundle).get("expected.yaml")
    if exp_file is None:
        raise FileNotFoundError("private/expected.yaml missing")
    return {k: Decimal(str(v)) for k, v in yaml.safe_load(exp_file).items()}


def scenario_plan(pkg: LabPackage, expected: dict[str, Decimal], engine: str | None = None) -> list[tuple[str, str]]:
    """(engine, scenario) pairs in run order. engine=None: every engine the lab may run on (all primary
    engines for 'default' labs). A break-fix lab additionally proves that a Reset reproduces its baseline."""
    engines = [engine] if engine else list(emulators.candidates(pkg.definition.runtime.emulator))
    names = [n for n in ("empty", "partial", "solution") if n in expected]
    if pkg.definition.kind == "break_fix":
        names.append(RESET)
    return [(eng, name) for eng in engines for name in names]


async def check_pack(pack: str | Path | LabPackage, runner: RunnerClient | None = None,
                     engine: str | None = None, *, expected: dict[str, Decimal] | None = None,
                     sandbox_id_for: Callable[[str], str] | None = None,
                     on_result: Callable[[ScenarioResult], Awaitable[None]] | None = None) -> list[ScenarioResult]:
    """Run every scenario of a pack (a directory, or an in-memory `LabPackage` from the Lab Builder).
    `expected` overrides private/expected.yaml; `sandbox_id_for("<engine>/<scenario>")` fixes the sandbox ids
    (the builder records them so the reconciler leaves them alone); `on_result` sees each result as it lands."""
    pkg = pack if isinstance(pack, LabPackage) else load_pack(pack)
    expected = expected if expected is not None else expected_scores(pkg)
    runner = runner or get_runner()
    out = []
    for eng, name in scenario_plan(pkg, expected, engine):
        key = f"{eng}/{name}"
        r = await run_scenario(runner, pkg, name, expected["empty"] if name == RESET else expected[name], eng,
                               sandbox_id_for(key) if sandbox_id_for else None)
        r.name = key
        out.append(r)
        if on_result is not None:
            await on_result(r)
    return out


async def _main(args: list[str]) -> int:
    engine = None
    if "--engine" in args:
        i = args.index("--engine")
        engine = args[i + 1]
        args = args[:i] + args[i + 2:]
    paths = args or [f"{get_settings().labs_dir}/s3-basics"]
    ok = True
    for p in paths:
        print(f"== labtest {p}")
        for r in await check_pack(p, engine=engine):
            mark = "PASS" if r.ok else "FAIL"
            ok &= r.ok
            print(f"  [{mark}] {r.name:<16} expected {r.expected}  got {r.actual}   {r.detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))

"""Load and validate a lab pack directory:

    labs/<id>/lab.yaml        definition (schema_version required)
    labs/<id>/public/**       optional: setup scripts/assets (may be sent to the runner)
    labs/<id>/private/**      solution.sh, partial.sh, expected.yaml, notes (NEVER leaves tooling)

Bundles are deterministic tar archives (sorted, mtime 0, uid 0) so a re-import of unchanged content
yields the same hashes (PLAN §7 immutability rule)."""

from __future__ import annotations

import hashlib
import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from ..grader import registry
from ..runtime import emulators
from .render import compute_variables, render_task
from .schema import LabDefinition, LabValidationError, parse_definition

SAMPLE_SHORT_ID = "abc123"


@dataclass(frozen=True)
class LabPackage:
    definition: LabDefinition
    yaml_text: str
    public_bundle: bytes
    private_bundle: bytes

    @property
    def public_sha256(self) -> str:
        return hashlib.sha256(self.public_bundle).hexdigest()

    @property
    def private_sha256(self) -> str:
        return hashlib.sha256(self.private_bundle).hexdigest()

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(f"{self.public_sha256}:{self.private_sha256}".encode()).hexdigest()


def _tar(files: list[tuple[str, bytes, int]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data, mode in sorted(files):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.mtime, ti.uid, ti.gid = len(data), mode, 0, 0, 0
            ti.uname = ti.gname = ""
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _collect(root: Path, sub: str) -> list[tuple[str, bytes, int]]:
    base = root / sub
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_file():
            rel = p.relative_to(base).as_posix()
            data = p.read_bytes()
            if rel.endswith(".sh"):
                data = data.replace(b"\r\n", b"\n")  # authored on Windows is fine
            out.append((rel, data, 0o755 if rel.endswith(".sh") else 0o644))
    return out


def tar_members(bundle: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(bundle)) as tf:
        return {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}  # type: ignore[union-attr]


def validate_definition(d: LabDefinition, public_files: set[str]) -> list[str]:
    """Semantic validation beyond the schema: known+supported checks, param types (after rendering
    with a sample student), capability support levels, setup script presence."""
    errors: list[str] = []
    ops: set[str] = set(d.requires)
    try:
        variables = compute_variables(d, SAMPLE_SHORT_ID)
    except Exception as e:  # jinja errors
        return [f"variables: {e}"]
    for task in d.tasks:
        try:
            rendered = render_task(task, variables)
        except Exception as e:
            errors.append(f"task {task.id}: template error: {e}")
            continue
        for i, c in enumerate(rendered.checks):
            where = f"task {task.id} check {i + 1} ({c.type})"
            try:
                defn = registry.get(c.type)
            except KeyError:
                errors.append(f"{where}: unknown check type")
                continue
            try:
                defn.ensure_supported()
            except registry.NotSupportedInSlice as e:
                errors.append(f"{where}: {e}")
                continue
            try:
                defn.params_model.model_validate(c.params)
            except ValidationError as e:
                errors += [f"{where}: {'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
            ops.update(defn.reads)
            svc = c.type.split(".")[0]
            if svc not in d.services:
                errors.append(f"{where}: service {svc!r} is not listed in services")
    for engine in emulators.candidates(d.runtime.emulator):
        bad = emulators.get(engine).capabilities.unusable(sorted(ops))
        if bad:
            errors.append(f"unsupported emulator operations on {engine} (see capabilities): " + ", ".join(bad))
    if d.setup and d.setup.script not in public_files:
        errors.append(f"setup script public/{d.setup.script} not found")
    return errors


def load_pack(path: str | Path) -> LabPackage:
    root = Path(path)
    yml = root / "lab.yaml"
    if not yml.is_file():
        raise LabValidationError([f"{yml} not found"])
    text = yml.read_text(encoding="utf-8").replace("\r\n", "\n")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise LabValidationError([f"lab.yaml is not valid YAML: {e}"]) from e
    definition = parse_definition(data)
    public_files = _collect(root, "public")
    errors = validate_definition(definition, {n for n, _, _ in public_files})
    if errors:
        raise LabValidationError(errors)
    public = _tar([("lab.yaml", text.encode(), 0o644)] + [(f"public/{n}", d, m) for n, d, m in public_files])
    private = _tar(_collect(root, "private"))
    return LabPackage(definition, text, public, private)


SETUP_WRAPPER = "_cloudlabs_setup.sh"


def setup_job(pkg_public_bundle: bytes, definition: LabDefinition, variables: dict[str, str]) -> dict | None:
    """Runner job spec for the lab's setup script, built only from the PUBLIC bundle plus a generated wrapper
    that exports the session's variables in upper case (`$BUCKET`, `$STUDENT_SHORT_ID`, ...) — the same
    convention as the private labtest scripts. Break-fix labs use it to create each student's broken state."""
    import base64
    import shlex
    if not definition.setup:
        return None
    exports = "".join(f"export {k.upper()}={shlex.quote(str(v))}\n" for k, v in sorted(variables.items()))
    wrapper = f"#!/bin/bash\nset -euo pipefail\n{exports}cd public\nbash {shlex.quote(definition.setup.script)}\n"
    files = tar_members(pkg_public_bundle)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in {**files, SETUP_WRAPPER: wrapper.encode()}.items():
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), 0o755 if name.endswith(".sh") else 0o644
            tf.addfile(ti, io.BytesIO(data))
    raw = buf.getvalue()
    return {"bundle_b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest(),
            "script": SETUP_WRAPPER, "timeout_s": definition.setup.timeout_s}

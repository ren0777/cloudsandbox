"""Lab Builder drafts (phase 8), pure helpers: draft content ⇄ pack files, YAML round-trip, row-level
validation errors, scenario expectations and tar.gz packs for export/import. No database access here.

Draft content = {"lab": <schema-v1 dict>, "files": {"private/solution.sh": text, ..., "public/...": text}}.
Only EDITABLE_FILES may be changed by the author; any other file (a setup script or private asset from a
cloned or imported pack) is carried unchanged and shown read-only (v1 does not author setup scripts)."""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
import zlib
from decimal import Decimal, InvalidOperation
from typing import Any

import yaml

from .package import MAX_FILE_BYTES, MAX_PACK_FILES, LabPackage, check_files, pack_files, pack_from_files
from .schema import LabDefinition, LabValidationError

EDITABLE_FILES: tuple[str, ...] = ("private/solution.sh", "private/partial.sh", "private/expected.yaml",
                                   "private/notes.md")
SCENARIOS: tuple[str, ...] = ("empty", "partial", "solution")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024   # compressed pack upload
MAX_LAB_JSON_BYTES = 256 * 1024


# ------------------------------------------------------------------------------------------- YAML
class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, s: str) -> yaml.ScalarNode:
    # Multi-line text (story, descriptions) as literal blocks, so the YAML view reads like a hand-written pack.
    style = "|" if "\n" in s else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


_Dumper.add_representer(str, _str)


def lab_to_yaml(lab: dict[str, Any]) -> str:
    return yaml.dump(lab, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)


def safe_yaml(text: str | bytes, name: str) -> Any:
    """yaml.safe_load for author-supplied text, refusing aliases (`*ref`): a few KB of nested aliases expand
    exponentially once serialised ("billion laughs"), and lab packs never need them."""
    try:
        if any(isinstance(ev, yaml.AliasEvent) for ev in yaml.parse(text, Loader=yaml.SafeLoader)):
            raise LabValidationError([f"{name}: YAML aliases (*name) are not supported; write the value out"])
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise LabValidationError([f"{name} is not valid YAML: {e}"]) from e


def yaml_to_lab(text: str) -> dict[str, Any]:
    """Parse the author's YAML into the draft's lab dict. Only syntax and shape are checked here; schema
    problems are reported by validation, like any other draft edit."""
    data = safe_yaml(text.replace("\r\n", "\n"), "lab.yaml")
    if not isinstance(data, dict):
        raise LabValidationError(["lab.yaml must be a mapping"])
    try:  # drafts are stored as JSON: refuse YAML-only values (dates, binary) up front
        return json.loads(json.dumps(data))
    except (TypeError, ValueError) as e:
        raise LabValidationError([f"lab.yaml: {e} (quote dates and other special values)"]) from e


# ------------------------------------------------------------------------------------- pack files
def draft_files(content: dict[str, Any]) -> dict[str, bytes]:
    files = {"lab.yaml": lab_to_yaml(content["lab"]).encode()}
    files.update({p: t.encode() for p, t in content.get("files", {}).items()})
    return files


def content_from_files(files: dict[str, bytes]) -> dict[str, Any]:
    """Draft content from pack files (clone, import). The pack may be schema-invalid (the author fixes it
    in the builder), but paths, sizes and encodings are checked like any pack."""
    errors = check_files(files)
    text: dict[str, str] = {}
    for name, data in files.items():
        try:
            text[name] = data.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{name}: only UTF-8 text files are supported in the Lab Builder")
    if errors:
        raise LabValidationError(errors)
    lab = yaml_to_lab(text.pop("lab.yaml"))
    return {"lab": lab, "files": {n: t.replace("\r\n", "\n") if n.endswith(".sh") else t
                                  for n, t in sorted(text.items())}}


def content_from_bundles(public_bundle: bytes, private_bundle: bytes) -> dict[str, Any]:
    return content_from_files(pack_files(public_bundle, private_bundle))


def blank_content(slug: str, title: str) -> dict[str, Any]:
    lab = {
        "schema_version": 1, "id": slug, "version": "1.0.0", "title": title,
        "summary": "", "story": "Describe the scenario here. Your bucket is **{{ bucket }}**.\n",
        "services": ["s3"], "runtime": {"emulator": "default"}, "duration_minutes": 30, "max_attempts": 3,
        "variables": {"bucket": "lab-{{ student_short_id }}"},
        "requires": ["s3:CreateBucket"],
        "tasks": [{"id": "create-bucket", "title": "Create the S3 bucket {{ bucket }}", "hints": [], "marks": 100,
                   "checks": [{"type": "s3.bucket_exists", "bucket": "{{ bucket }}"}]}],
    }
    files = {
        "private/solution.sh": "#!/bin/bash\n# Reference solution (never shown to students).\n"
                               "set -euo pipefail\naws s3 mb \"s3://$BUCKET\"\n",
        "private/expected.yaml": "# Scores the test run must produce (PRIVATE)\nempty: \"0.00\"\n"
                                 "solution: \"100.00\"\n",
        "private/notes.md": "",
    }
    return {"lab": lab, "files": files}


def apply_edit(content: dict[str, Any], lab: dict[str, Any] | None, files: dict[str, str] | None) -> dict[str, Any]:
    """New draft content after an author edit. Only EDITABLE_FILES can change; an empty text removes one."""
    new_files = dict(content.get("files", {}))
    errors = []
    for name, text in (files or {}).items():
        if name not in EDITABLE_FILES:
            if new_files.get(name) != text:
                errors.append(f"{name}: read-only in the Lab Builder (only {', '.join(EDITABLE_FILES)} can change)")
            continue
        if len(text.encode()) > MAX_FILE_BYTES:
            errors.append(f"{name}: larger than {MAX_FILE_BYTES // 1024} KB")
        if text.strip():
            new_files[name] = text.replace("\r\n", "\n") if name.endswith(".sh") else text
        else:
            new_files.pop(name, None)
    new_lab = content["lab"] if lab is None else lab
    if len(yaml.safe_dump(new_lab).encode()) > MAX_LAB_JSON_BYTES:
        errors.append(f"lab: larger than {MAX_LAB_JSON_BYTES // 1024} KB")
    if errors:
        raise LabValidationError(errors)
    return {"lab": new_lab, "files": dict(sorted(new_files.items()))}


# ------------------------------------------------------------------------------------ validation
def expectations(files: dict[str, bytes], d: LabDefinition) -> tuple[dict[str, Decimal], list[str]]:
    """Test-run scenarios for the publish gate (owner decision): an untouched sandbox scores 0 and the
    reference solution full marks; a partial scenario is optional and needs private/partial.sh."""
    errors: list[str] = []
    if not files.get("private/solution.sh", b"").strip():
        errors.append("private/solution.sh: a reference solution is required to test and publish the lab")
    has_partial = bool(files.get("private/partial.sh", b"").strip())
    raw: Any = {}
    if "private/expected.yaml" in files:
        try:
            raw = safe_yaml(files["private/expected.yaml"], "private/expected.yaml") or {}
        except LabValidationError as e:
            errors += e.errors
        if not isinstance(raw, dict):
            errors.append("private/expected.yaml: must be a mapping like {empty: 0, partial: 50, solution: 100}")
            raw = {}
    expected: dict[str, Decimal] = {"empty": Decimal("0"), "solution": d.max_score}
    for k, v in raw.items():
        if k not in SCENARIOS:
            errors.append(f"private/expected.yaml: unknown scenario {k!r} (known: {', '.join(SCENARIOS)})")
            continue
        try:
            expected[k] = Decimal(str(v))
        except InvalidOperation:
            errors.append(f"private/expected.yaml: {k}: {v!r} is not a number")
    if expected["empty"] != 0:
        errors.append("private/expected.yaml: empty: an untouched sandbox must score 0")
    if expected["solution"] != d.max_score:
        errors.append(f"private/expected.yaml: solution: the reference solution must score full marks "
                      f"({d.max_score})")
    if has_partial and "partial" not in expected:
        errors.append("private/expected.yaml: partial: give the score private/partial.sh should reach")
    if "partial" in expected:
        if not has_partial:
            errors.append("private/expected.yaml: partial: there is no private/partial.sh to test")
        elif not (0 < expected["partial"] < d.max_score):
            errors.append(f"private/expected.yaml: partial: must be between 0 and {d.max_score} (exclusive)")
    return {k: v.quantize(Decimal("0.01")) for k, v in expected.items()}, errors


def package(content: dict[str, Any]) -> LabPackage:
    """The draft as a validated lab pack (raises LabValidationError)."""
    return pack_from_files(draft_files(content))


def build(content: dict[str, Any]) -> tuple[LabPackage | None, list[str]]:
    """(package, errors). The package is None when the pack itself is invalid; errors also include
    scenario problems that only block testing and publishing."""
    try:
        pkg = package(content)
    except LabValidationError as e:
        return None, list(e.errors)
    return pkg, expectations(draft_files(content), pkg.definition)[1]


_CHECK_ERR = re.compile(r"^task (?P<task>\S+) check (?P<check>\d+) \((?P<type>[^)]+)\): "
                        r"(?:(?P<field>[A-Za-z_][\w.]*): )?(?P<msg>.*)$", re.S)
_TASK_ERR = re.compile(r"^task (?P<task>\S+): (?P<msg>.*)$", re.S)
_LOC_ERR = re.compile(r"^(?P<loc>[A-Za-z_][\w.]*|(?:public|private)/[^:]+|lab\.yaml): (?P<msg>.*)$", re.S)


def row_error(message: str, lab: dict[str, Any]) -> dict[str, Any]:
    """A validation message as a row the builder can place next to the field: {message, loc, task, check,
    field}. `task` is a task id, `check` a 1-based check number, `loc` a dotted schema path or a file."""
    row: dict[str, Any] = {"message": message, "loc": None, "task": None, "check": None, "field": None}
    if m := _CHECK_ERR.match(message):
        row.update(task=m["task"], check=int(m["check"]), field=m["field"])
    elif m := _TASK_ERR.match(message):
        row.update(task=m["task"])
    elif m := _LOC_ERR.match(message):
        row["loc"] = m["loc"]
        parts = m["loc"].split(".")
        if parts[0] == "tasks" and len(parts) > 1 and parts[1].isdigit():
            tasks = lab.get("tasks") if isinstance(lab.get("tasks"), list) else []
            i = int(parts[1])
            if i < len(tasks) and isinstance(tasks[i], dict):
                row["task"] = tasks[i].get("id")
            if len(parts) > 3 and parts[2] == "checks" and parts[3].isdigit():
                row["check"] = int(parts[3]) + 1
                row["field"] = ".".join(parts[4:]) or None
            else:
                row["field"] = ".".join(parts[2:]) or None
    return row


# ---------------------------------------------------------------------------------- tar.gz packs
def to_targz(files: dict[str, bytes], root: str) -> bytes:
    """Deterministic tar.gz of a pack under `root/` (sorted, mtime 0), as exported to instructors."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in sorted(files.items()):
            ti = tarfile.TarInfo(f"{root}/{name}")
            ti.size, ti.mtime, ti.uid, ti.gid = len(data), 0, 0, 0
            ti.mode = 0o755 if name.endswith(".sh") else 0o644
            ti.uname = ti.gname = ""
            tf.addfile(ti, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def from_targz(data: bytes) -> dict[str, bytes]:
    """Pack files from an uploaded .tar.gz (or .tar). lab.yaml may be at the top level or inside one
    top-level folder (as exported). Only regular files are read; links, devices and oversized members are
    refused before anything is extracted."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise LabValidationError([f"upload larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"])
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            return _read_pack(tf)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as e:
        raise LabValidationError([f"not a .tar.gz lab pack: {e}"]) from e


def _read_pack(tf: tarfile.TarFile) -> dict[str, bytes]:
    members = tf.getmembers()
    errors: list[str] = []
    regular = []
    for m in members:
        if m.isdir():
            continue
        if not m.isfile():
            errors.append(f"{m.name}: only regular files are allowed (no links or devices)")
        elif m.size > MAX_FILE_BYTES:
            errors.append(f"{m.name}: larger than {MAX_FILE_BYTES // 1024} KB")
        else:
            regular.append(m)
    if len(regular) > MAX_PACK_FILES:
        errors.append(f"too many files (limit {MAX_PACK_FILES})")
    if errors:
        raise LabValidationError(errors)
    names = [m.name.removeprefix("./") for m in regular]
    prefix = ""
    if "lab.yaml" not in names:
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) == 1 and f"{next(iter(tops))}/lab.yaml" in names:
            prefix = f"{next(iter(tops))}/"
    files: dict[str, bytes] = {}
    for m, n in zip(regular, names):
        if not n.startswith(prefix):
            errors.append(f"{n}: outside the pack folder {prefix.rstrip('/')}")
            continue
        f = tf.extractfile(m)
        files[n[len(prefix):]] = f.read() if f else b""
    if errors:
        raise LabValidationError(errors)
    return files

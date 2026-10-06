"""Architecture invariants that must never break (CLAUDE.md / PLAN §10, maintenance M6).

The API control plane **never** imports the Docker SDK: only the Runner Agent owns the Docker socket,
and the API reaches sandboxes exclusively through `RunnerClient` (HMAC-signed HTTP). `app/main.py`
and `app/auth/policy.py` already referenced this file; it did not exist, so the invariant was only
documented, not enforced.

The scan is static (AST), so comments or strings mentioning docker can't produce a false positive.
The non-vacuity tests prove the scanner flags a real violation and is looking at the real API tree.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]  # services/api in the repo; /srv in the test container
API = API_ROOT / "app"
SERVICES = API_ROOT.parent
RUNNER = SERVICES / "runner" / "app"  # present in the repo/CI; not mounted in the API test container


def _imports_docker(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "docker" or alias.name.startswith("docker.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "docker" or node.module.startswith("docker."):
                return True
    return False


def _docker_importers(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*.py")) if _imports_docker(path)]


def test_api_never_imports_the_docker_sdk():
    offenders = [str(path.relative_to(API_ROOT)) for path in _docker_importers(API)]
    assert not offenders, (
        "the API must talk to Docker only through the Runner Agent (RunnerClient); "
        f"Docker SDK imports found in: {offenders}"
    )


def test_the_scan_covers_the_api_tree():
    """A scan pointed at the wrong directory would pass vacuously. 99 modules today; fail if the
    tree shrinks implausibly."""
    modules = list(API.rglob("*.py"))
    assert len(modules) >= 50, f"only {len(modules)} API modules found under {API} — wrong root?"


def test_the_scanner_would_catch_a_violation(tmp_path):
    """Non-vacuity: a synthetic file that imports the Docker SDK must be flagged."""
    violation = tmp_path / "violation.py"
    violation.write_text("import docker\n", encoding="utf-8")
    assert _docker_importers(tmp_path) == [violation]
    (tmp_path / "innocent.py").write_text("from app.runtime.runner_client import RunnerClient\n",
                                          encoding="utf-8")
    assert _docker_importers(tmp_path) == [violation]


def test_the_runner_owns_the_docker_sdk():
    """The other half of the invariant: the runner *does* import the Docker SDK. Skipped in the API
    test container (runner sources are not mounted); CI and a repo checkout run it."""
    if not RUNNER.exists():
        pytest.skip("runner sources are not part of this checkout (API test container)")
    found = [str(path) for path in _docker_importers(RUNNER)]
    assert found, f"expected Docker SDK imports under {RUNNER} — the architecture scanner is broken"

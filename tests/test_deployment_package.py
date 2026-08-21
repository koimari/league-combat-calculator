"""Deployment-package contract for the beta metrics scorecard (issue #144).

The production artifact (``.vercelignore`` / Dockerfile) ships only ``src/``,
``data/``, ``static/``, ``templates/`` plus root manifests — ``scripts/`` is
excluded.  Before the fix, ``GET /api/metrics`` lazily imported
``scripts.beta_metrics`` and 503'd in the deployed shape while passing
locally because app.py inserted the repo root onto ``sys.path``.

This test rebuilds that exact shape in a temp directory and runs a subprocess
with ONLY the package root on ``sys.path``: every route dependency must
import, and the scorecard endpoint must return 200 (never the
"Metrics module unavailable" 503).  The CLI and endpoint share
``src.metrics.compute_scorecard``, so the subprocess also asserts their
payloads agree (modulo the timestamp).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

# Mirrors .vercelignore (and the Dockerfile COPY set): excluded directory
# names and file suffixes at any depth.
_IGNORED_NAMES = {
    ".git",
    ".venv",
    ".vercel",
    ".playwright",
    ".playwright-cli",
    ".pytest_cache",
    "__pycache__",
    "tests",
    "scripts",
    "docs",
    "output",
    "prototypes",
    "vendor",
}
_IGNORED_SUFFIXES = (".pyc", ".blend", ".blend1", ".psd", ".mov")

_ROUTE_DEPENDENCIES = [
    "src.calculator.application_errors",
    "src.calculator.calculate",
    "src.calculator.certainty",
    "src.calculator.data_fetcher",
    "src.calculator.item_effects",
    "src.calculator.rune_effects",
    "src.calculator.item_coverage",
    "src.calculator.ally_effects",
    "src.calculator.loadout_rules",
    "src.calculator.defensive_effects",
    "src.calculator.participant_timeline",
    "src.calculator.champions",
    "src.calculator.capabilities",
    "src.calculator.optimizer",
    "src.calculator.stats",
    "src.calculator.timeline_coverage",
    "src.calculator.scenario",
    "src.calculator.role_quests",
    "src.calculator.pipeline",
    "src.calculator.public_response",
    "src.calculator.request_parsing",
    "src.calculator.validation_receipts",
    "src.calculator.bis",
    "src.rate_limit",
    "src.db",
    "src.metrics",
]


def _ignored(rel_path: Path) -> bool:
    """Apply the .vercelignore semantics used by the production build."""
    return any(
        part in _IGNORED_NAMES for part in rel_path.parts
    ) or rel_path.name.endswith(_IGNORED_SUFFIXES)


def _build_package(destination: Path) -> None:
    """Copy the deployable file set (src/, data/, static/, templates/ + root
    manifests) into ``destination``, skipping everything .vercelignore drops."""
    destination.mkdir(parents=True)
    for child in ROOT.iterdir():
        rel = child.relative_to(ROOT)
        if _ignored(rel):
            continue
        if child.is_dir():
            shutil.copytree(
                child,
                destination / rel,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(child, destination / rel)
    # Guard: the deployed shape must really be missing scripts/.
    assert not (destination / "scripts").exists()


@pytest.fixture(scope="module")
def deployment_package(tmp_path_factory):
    """One package per module: copying src/ + data/ is ~30 MB."""
    package = tmp_path_factory.mktemp("vercel-pkg") / "pkg"
    _build_package(package)
    return package


def _run_in_package(package: Path, code: str) -> str:
    """Run ``code`` in a subprocess with only the package on sys.path."""
    env = dict(os.environ)
    # Strip any ambient PYTHONPATH so the repo cannot leak into the package.
    env.pop("PYTHONPATH", None)
    env["PYTHONPATH"] = str(package)
    # cwd is a scratch dir outside the repo; sys.path[0] is that cwd.
    cwd = package.parent
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_deployment_package_imports_every_route_dependency(deployment_package):
    """The packaged artifact imports the app and every route dependency with
    no repo path on sys.path — including the runtime ``metrics`` module."""
    imports = "; ".join(f"import {name}" for name in _ROUTE_DEPENDENCIES)
    code = f"""
import os
import sys
import importlib.util
from pathlib import Path
scripts_spec = importlib.util.find_spec("scripts")
package_root = Path(os.environ["PYTHONPATH"]).resolve()
if scripts_spec is not None:
    locations = [Path(value).resolve() for value in (scripts_spec.submodule_search_locations or [])]
    assert package_root not in locations and not any(package_root in value.parents for value in locations), "scripts must not ship"
# Importing src.app first mirrors the production entrypoint; every route
# dependency must then resolve from the packaged artifact alone under the
# single ``src.*`` namespace (issue #164).
import src.app
{imports}
print("ALL-IMPORTS-OK")
"""
    output = _run_in_package(deployment_package, code)
    assert "ALL-IMPORTS-OK" in output


def test_deployment_package_metrics_endpoint_returns_scorecard(
    deployment_package,
):
    """GET /api/metrics in the deployed shape returns the scorecard — never
    the "Metrics module unavailable" 503 that shipped before the fix."""
    code = """
import json
import src.app as app_module
app_module.app.config["TESTING"] = True
app_module.app.config["RATE_LIMIT_ENABLED"] = False
client = app_module.app.test_client()
response = client.get("/api/metrics")
assert response.status_code == 200, (response.status_code, response.get_data(as_text=True))
body = response.get_json()
assert set(body) >= {"generated_at", "beta", "criteria", "gate"}
assert set(body["criteria"]) == {"retention", "receipts", "bias", "staleness"}
assert body["gate"]["status"] in {"pass", "pending", "fail"}
print("METRICS-OK", json.dumps(body))
"""
    output = _run_in_package(deployment_package, code)
    assert "METRICS-OK" in output


def test_deployment_package_cli_and_endpoint_share_the_gate(
    deployment_package,
):
    """The CLI and the endpoint serve byte-identical criteria/receipts from
    the same ``metrics.compute_scorecard`` (modulo the generated timestamp)."""
    code = """
import json
import src.app as app_module
app_module.app.config["TESTING"] = True
app_module.app.config["RATE_LIMIT_ENABLED"] = False
client = app_module.app.test_client()
endpoint_body = client.get("/api/metrics").get_json()
from src import metrics
cli_body = metrics.compute_scorecard()
# ``generated_at`` and the beta window bounds embed the evaluation moment;
# normalize them so the shared criteria/receipt schema is what is compared.
for body in (endpoint_body, cli_body):
    body.pop("generated_at", None)
    body["beta"].pop("start", None)
    body["beta"].pop("end", None)
assert endpoint_body == cli_body, "endpoint and CLI scorecards diverged"
print("CLI-ENDPOINT-PARITY-OK")
"""
    output = _run_in_package(deployment_package, code)
    assert "CLI-ENDPOINT-PARITY-OK" in output

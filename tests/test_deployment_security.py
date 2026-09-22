"""Keep production hardening visible and regression-tested."""

import re
from pathlib import Path


def test_container_is_pinned_minimal_nonroot_and_health_checked():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "-slim@sha256:" in dockerfile
    assert "COPY requirements-runtime.txt" in dockerfile
    assert "COPY requirements.txt" not in dockerfile
    assert "apt-get update" in dockerfile
    assert "apt-get upgrade --yes" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/healthz" in dockerfile
    assert "--timeout 30" in dockerfile


def test_runtime_manifest_excludes_local_tools():
    runtime_input = Path("requirements-runtime.in").read_text(encoding="utf-8")
    runtime_lock = Path("requirements-runtime.txt").read_text(encoding="utf-8")

    assert "Flask==3.1.3" in runtime_input
    gunicorn_pin = next(
        line.strip()
        for line in runtime_input.splitlines()
        if line.startswith("gunicorn==")
    )
    assert gunicorn_pin in runtime_lock
    for local_only in ("pytest", "pylint", "bandit", "requests", "lxml"):
        assert local_only not in runtime_lock.lower()
    assert "--hash=sha256:" in runtime_lock


def test_ci_covers_net_new_main_branch_and_uses_immutable_actions():
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert "push:\n    branches: [main]\n" in workflow
    assert "pull_request:\n    branches: [main, chore/sightline-zero]\n" in workflow
    assert "aquasecurity/trivy-action@ed142fd" in workflow
    assert "actions/checkout@v" not in workflow
    assert "actions/setup-python@v" not in workflow


def test_the_security_gates_run_in_the_jobs_that_own_them():
    """The commands moved into ci/ with the rest of each job's checks
    (docs/ci-local.md); what they must still cover is pinned here, in the
    spelling each script's ``run_step`` label uses."""
    static = Path("ci/static.sh").read_text(encoding="utf-8")
    container = Path("ci/container.sh").read_text(encoding="utf-8")

    assert "pip-audit -r requirements.txt" in static
    assert "pip-audit -r requirements-runtime.txt" in static
    assert "bandit -r src -ll" in static
    assert 'docker build --tag "$IMAGE" .' in container
    assert 'docker exec "$NAME" id -u' in container
    assert "/api/calculate" in container
    assert ".State.Health.Status" in container
    assert "Metrics module unavailable" in container


def test_the_image_the_container_job_builds_is_the_one_trivy_scans():
    """Two homes that must agree: the tag ci/container.sh builds and the
    ``image-ref`` the scan action reads, two steps later in the workflow."""
    container = Path("ci/container.sh").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    image = re.search(r'^IMAGE="(\S+)"', container, re.MULTILINE)
    assert image, "ci/container.sh names no image"
    assert f"image-ref: {image[1]}" in workflow

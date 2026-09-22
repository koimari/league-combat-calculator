"""One home per CI fact, and the readers that must agree with it.

A gate command lives in the ``ci/`` script that owns its job.  The workflow
provisions a runner and calls that script, the ``Makefile`` names a target per
job, and ``docs/ci-local.md`` maps the three together, so the only way a gate
can differ between hosted and local CI is a script that does not run at all.

The interpreter has the same shape: ``.python-version`` is its one home, and
the Dockerfile tag and every workflow job derive from it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
CI_DOC = (ROOT / "docs" / "ci-local.md").read_text(encoding="utf-8")
PYTHON_VERSION = (ROOT / ".python-version").read_text(encoding="utf-8").strip()

#: A workflow job and the ``ci/`` script that owns its checks.
JOB_SCRIPTS = {
    "shared-ui": "ci/shared_ui.sh",
    "test": "ci/test.sh",
    "static": "ci/static.sh",
    "coverage-census": "ci/coverage_census.sh",
    "container": "ci/container.sh",
}

#: The one command a workflow step may run beside a job's script: provisioning
#: is the runner's own work and has no local equivalent.
PROVISIONING = ("pip install -r requirements.txt",)


def _jobs() -> dict[str, str]:
    """Each job's block, keyed by name: a name at two spaces under ``jobs:``."""
    body = WORKFLOW.partition("\njobs:\n")[2]
    starts = list(re.finditer(r"^ {2}([a-z-]+):$", body, re.MULTILINE))
    bounds = [match.start() for match in starts] + [len(body)]
    return {
        match[1]: body[bounds[index] : bounds[index + 1]]
        for index, match in enumerate(starts)
    }


def _runs(block: str) -> list[str]:
    """Every shell command a job's steps run."""
    return [line.strip() for line in re.findall(r"^ +run: (.+)$", block, re.MULTILINE)]


def test_every_workflow_job_runs_the_script_that_owns_its_checks():
    """The workflow spells no gate command of its own."""
    jobs = _jobs()
    assert set(jobs) == set(JOB_SCRIPTS), sorted(jobs)
    for job, script in JOB_SCRIPTS.items():
        commands = _runs(jobs[job])
        assert f"bash {script}" in commands, (job, commands)
        extra = [
            command
            for command in commands
            if command != f"bash {script}" and command not in PROVISIONING
        ]
        assert extra == [], (job, extra)


def test_every_job_has_a_make_target_that_runs_the_same_script():
    """``make ci-<job>`` is the local half, and ``ci-full`` runs them all."""
    for job, script in JOB_SCRIPTS.items():
        assert f"ci-{job}:\n\tbash {script}\n" in MAKEFILE, job
    full = MAKEFILE.partition("\nci-full:\n")[2].partition("\nci-")[0]
    listed = re.search(r"for job in ([a-z_ ]+); do", full)
    assert listed, full
    assert sorted(f"ci/{name}.sh" for name in listed[1].split()) == sorted(
        JOB_SCRIPTS.values()
    )


def test_the_local_ci_doc_maps_every_job_to_its_script_and_target():
    for job, script in JOB_SCRIPTS.items():
        row = next(
            (line for line in CI_DOC.splitlines() if line.startswith(f"| `{job}`")),
            None,
        )
        assert row, job
        assert f"`{script}`" in row, row
        assert f"`ci-{job}`" in row, row


def test_the_workflow_reads_the_python_version_from_its_one_home():
    """Every ``setup-python`` step names the file, never the number."""
    assert re.findall(r"python-version-file: (\S+)", WORKFLOW) == [
        ".python-version"
    ] * (WORKFLOW.count("actions/setup-python@"))
    assert "python-version:" not in WORKFLOW


def test_the_image_runs_the_python_version_the_tests_run():
    """The tag stays spelled out beside the digest on a literal ``FROM``, the
    only form Dependabot bumps, so it is a reader that must be checked, and
    the comment above it cites this file, so moving the check dangles it."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    reference = re.search(r"^FROM (\S+)$", dockerfile, re.MULTILINE)
    assert reference, "the base image is not one literal FROM"
    assert re.fullmatch(
        rf"python:{re.escape(PYTHON_VERSION)}-slim@sha256:[0-9a-f]{{64}}", reference[1]
    ), reference[1]
    assert f"tests/{Path(__file__).name}" in dockerfile


def test_no_other_config_selects_an_interpreter_version():
    """A fifth home would drift silently; these spellings are how one starts."""
    selectors = re.compile(
        r"python:\d+\.\d+|--python[= ]\\?[\"']?\d+\.\d+"
        r"|^\s*(?:python-version|requires-python|target-version)\s*[:=]",
        re.MULTILINE,
    )
    for name in ("pyproject.toml", "Makefile", ".github/workflows/tests.yml"):
        found = selectors.findall((ROOT / name).read_text(encoding="utf-8"))
        assert found == [], (name, found)
    for script in sorted((ROOT / "ci").glob("*.sh")):
        found = selectors.findall(script.read_text(encoding="utf-8"))
        assert found == [], (script.name, found)

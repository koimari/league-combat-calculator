"""P0d: patch-day runbook deliverables exist and reference real automation.

The runbook is an operating procedure, not code, so the tests guard its
contract: the files exist, carry the required sections (SLA, steps 0-5,
escalation), and reference scripts that actually exist on disk.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

RUNBOOK = DOCS / "patch-day-runbook.md"
OPS = DOCS / "beta-operations.md"
ANNOUNCEMENT = DOCS / "patch-announcement-template.md"

REQUIRED_SCRIPTS = (
    "patch_update.py",
    "patch_regression.py",
)


def test_patch_day_runbook_exists_with_required_sections() -> None:
    """The runbook must cover SLA, every day-0 step, and escalations."""
    assert RUNBOOK.is_file(), f"{RUNBOOK} is missing"
    text = RUNBOOK.read_text(encoding="utf-8")
    for heading in (
        "## SLA",
        "## Step 0",
        "## Step 1",
        "## Step 2",
        "## Step 3",
        "## Step 4",
        "## Step 5",
        "## Escalation",
    ):
        assert heading in text, f"{heading} missing from {RUNBOOK.name}"


def test_patch_day_runbook_sla_numbers() -> None:
    """The SLA table must state the three clocks and the badge rule."""
    text = RUNBOOK.read_text(encoding="utf-8")
    for expected in ("< 4h", "< 24h", "< 72h", "stays visible until re-cert"):
        assert expected in text, f"SLA clause {expected!r} missing from runbook"


def test_patch_day_runbook_steps_reference_real_scripts() -> None:
    """Every automation script the runbook names must exist on disk."""
    text = RUNBOOK.read_text(encoding="utf-8")
    for script in REQUIRED_SCRIPTS:
        assert script in text, f"{script} not referenced by {RUNBOOK.name}"
        assert (ROOT / "scripts" / script).is_file(), f"scripts/{script} missing"


def test_patch_day_runbook_escalation_covers_rework_paths() -> None:
    """Escalation must address kit rework, item rework, and new items."""
    text = RUNBOOK.read_text(encoding="utf-8")
    for expected in ("champion kit rework", "Item rework", "New item added"):
        assert expected in text, f"escalation clause {expected!r} missing"


def test_beta_operations_weekly_checklist() -> None:
    """The weekly ops doc must exist and cover the five required items."""
    assert OPS.is_file(), f"{OPS} is missing"
    text = OPS.read_text(encoding="utf-8")
    for expected in (
        "Weekly Checklist",
        "/api/validation",
        "/api/feedback",
        "Backup verification",
        "30 minutes",
    ):
        assert expected in text, f"{expected!r} missing from {OPS.name}"


def test_patch_announcement_template_exists() -> None:
    """The announcement template must exist with early and final posts."""
    assert ANNOUNCEMENT.is_file(), f"{ANNOUNCEMENT} is missing"
    text = ANNOUNCEMENT.read_text(encoding="utf-8")
    assert "Early post" in text
    assert "Final post" in text
    assert "Changelog format" in text

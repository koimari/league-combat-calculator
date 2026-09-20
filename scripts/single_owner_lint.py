"""Three facts of `src/calculator`, each with exactly one owner in the tree.

Every rule here is the same shape: a symbol whose second implementation would
have no symptom, held to one home by a scan rather than by review.

* `EventSlots` is constructed once, for the module singleton `EVENT_SLOTS`.
  Two registries hand two numberings to actions that meet inside one walk,
  so two events answer to one integer with nothing to show for it.
* A shield pool is moved only by `shield_ledger`.  Direct arithmetic on
  `.physical_shield`, `.magic_shield` or `.general_shield` anywhere else is a
  second implementation of the absorption order.
* A walk-authored heal reads its timestamp through
  `survival.actions.scheduled_heal_time`.  Both ledgers read it, and a heal
  that lost its stamp sorted to the fight's open rather than failing.

    python scripts/single_owner_lint.py

`tests/test_event_slots.py`, `tests/test_issue_159.py` and
`tests/test_transition_rank.py` each import the rule they own.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lint_report import report

ROOT = Path(__file__).resolve().parent.parent
CALCULATOR = ROOT / "src" / "calculator"

#: The one module allowed to construct the event-slot registry.
EVENT_SLOT_OWNER = "src/calculator/survival/event_slots.py"

#: The one module allowed to move a shield pool.
SHIELD_POOL_OWNER = CALCULATOR / "shield_ledger.py"

#: Draining or granting a pool is the transition's own business.
POOL_ARITHMETIC = re.compile(r"\.(physical|magic|general)_shield\s*(-=|\+=)")

#: The two ledgers that schedule a walk-authored heal, and the one read.
HEAL_TIMESTAMP_LEDGERS = ("score_state.py", "receipt_ledger.py")
HEAL_TIMESTAMP_READ = "scheduled_heal_time(heal_event)"
HEAL_TIMESTAMP_DEFAULT = 'heal_event.get("time", 0.0)'


def _sources(root: Path = CALCULATOR) -> list[tuple[str, str]]:
    """Every package module, as (path relative to the repo, source)."""
    return [
        (path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix())
    ]


def event_slot_constructions(root: Path = CALCULATOR) -> list[str]:
    """Every module that calls ``EventSlots()``, in tree order."""
    return [
        relative
        for relative, source in _sources(root)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EventSlots"
    ]


def shield_pool_arithmetic(root: Path = CALCULATOR) -> list[str]:
    """Every site outside the ledger that moves a shield pool directly."""
    owner = SHIELD_POOL_OWNER.relative_to(ROOT).as_posix()
    return [
        f"{relative}:{source[: match.start()].count(chr(10)) + 1}"
        for relative, source in _sources(root)
        if relative != owner
        for match in POOL_ARITHMETIC.finditer(source)
    ]


def heal_timestamp_readers(root: Path = CALCULATOR) -> list[str]:
    """Each ledger that does not read a heal's time through the one helper."""
    findings = []
    for module in HEAL_TIMESTAMP_LEDGERS:
        source = (root / "survival" / module).read_text(encoding="utf-8")
        if HEAL_TIMESTAMP_READ not in source:
            findings.append(f"{module} does not call {HEAL_TIMESTAMP_READ}")
        if HEAL_TIMESTAMP_DEFAULT in source:
            findings.append(f"{module} still reads {HEAL_TIMESTAMP_DEFAULT}")
    return findings


def check() -> list[str]:
    """Every finding across the three rules."""
    constructions = event_slot_constructions()
    findings = [
        f"{path} constructs a second EventSlots registry"
        for path in constructions
        if path != EVENT_SLOT_OWNER
    ]
    if EVENT_SLOT_OWNER not in constructions:
        findings.append(f"{EVENT_SLOT_OWNER} no longer builds the one registry")
    findings.extend(
        f"{site} moves a shield pool outside shield_ledger"
        for site in shield_pool_arithmetic()
    )
    findings.extend(heal_timestamp_readers())
    return findings


if __name__ == "__main__":
    raise SystemExit(report(check(), "OK: one owner for each of the three facts"))

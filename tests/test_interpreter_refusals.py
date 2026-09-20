"""Every registered interpreter refuses a rule of another family.

An interpreter handed a rule it cannot read must raise rather than return a
zero, because a zero is indistinguishable from a rule that priced to nothing.
The population is ``interpreters.INTERPRETERS`` itself, so a newly registered
(family, lane) pair is covered the moment it registers rather than when
somebody remembers to paste the check into its own test file.
"""

from __future__ import annotations

import pytest

from src.calculator.interpreters import INTERPRETERS
from src.calculator.item_behavior import (
    BehaviorRule,
    EngineLane,
    FightFacts,
    RuleFamily,
)
from src.calculator.item_behavior_catalog import (
    behavior_rules,
    build_context,
    rule_owners,
)

FACTS = FightFacts(
    level=18,
    fight_duration_seconds=5.0,
    target_bonus_health=0.0,
    holder_is_melee=True,
)


def _foreign_rule(family: RuleFamily) -> tuple[str, BehaviorRule]:
    """One declared rule of any family but *family*, with its owner."""
    for owner in sorted(rule_owners()):
        for rule in behavior_rules(owner):
            if rule.family is not family:
                return owner, rule
    raise AssertionError(f"the catalog declares nothing outside {family}")


@pytest.mark.parametrize(
    ("family", "lane"),
    sorted(INTERPRETERS, key=lambda pair: (pair[0].value, pair[1].value)),
    ids=lambda member: member.value,
)
def test_an_interpreter_refuses_a_rule_of_another_family(
    family: RuleFamily, lane: EngineLane
) -> None:
    owner, foreign = _foreign_rule(family)
    with pytest.raises(ValueError):
        INTERPRETERS[(family, lane)](foreign, build_context(owner, FACTS), lane)

"""The one selection over a build's declared rules.

Every interpreter asks the catalog the same question: which of the rules the
held owners declare belong to my family, in the order the items were bought.
Build order is the order the engine's own accumulator folds them in, so a
selection that reordered would move a float sum. Twelve modules each spelled
that comprehension with their own enum member baked in; this is the one place
it lives.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..item_behavior import BehaviorRule, RuleFamily
from ..item_behavior_catalog import behavior_rules


def rules_of(
    owners: Sequence[str],
    family: RuleFamily,
    payload_type: type | None = None,
) -> tuple[BehaviorRule, ...]:
    """Every rule of *family* the *owners* declare, in build order.

    *payload_type* narrows to one payload shape, for the families that carry
    more than one.
    """
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is family
        and (payload_type is None or isinstance(rule.payload, payload_type))
    )

"""Zeri — CP10.10 full-entry-reviewed packet module.

E5-2 fix — Spark Surge (E): the reviewed packet emitted the Lightning
Rounds per-round bonus ("Burst Fire Bonus Magic Damage" 22-30 + 20% AP)
as ONE flat magic hit and left the Lightning Rounds mechanic out of
scope.  The wiki prose (data/champions.json E): "Afterwards, she gains
Lightning Rounds for 5 seconds, empowering Burst Fire to deal bonus
magic damage to the first enemy hit, increased by 0% : 100% (+ 0% :
30%) (based on critical strike chance)".  Burst Fire fires 7 rounds
(the E2-sourced Total/per-round ratio on Q), so the E prices 7 rounds
of the per-round bonus, scaled linearly by crit chance between the two
sourced endpoints (x1 at 0% crit, x2.3 at 100% crit).  The dash itself
deals no damage.  Secondary targets ("Burst Fire Secondary Target
Damage" 80-100%) are outside this single-target model.
"""

from .reviewed_batch_10 import build_batch_module
from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Zeri")

# Burst Fire fires 7 rounds (Total Physical Damage / per-hit on Q,
# locked by tests/test_e2_dot_3.py); Lightning Rounds empowers each
# round's first-enemy hit.
_E_LIGHTNING_ROUNDS_ROUNDS = 7
# Lightning Rounds bonus "increased by 0% : 100% (+ 0% : 30%) (based on
# critical strike chance)": x2.3 at 100% crit -> 1 + 1.3 x crit_chance.
_E_BONUS_CRIT_MULTIPLIER_AT_MAX = 2.3


def _spark_surge(ctx: SlotCtx):
    """E: the dash plus 7 Lightning-Rounds-empowered Burst Fire rounds."""
    ability = ctx.ability("E", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    per_round = extract_named(
        ability, "Burst Fire Bonus Magic Damage", rank, ctx.stats, ctx.target
    )
    crit_chance = min(
        max(float(ctx.stats.get("critical_strike_chance", 0.0)) / 100.0, 0.0), 1.0
    )
    multiplier = 1.0 + (_E_BONUS_CRIT_MULTIPLIER_AT_MAX - 1.0) * crit_chance
    per_round *= multiplier
    total = per_round * _E_LIGHTNING_ROUNDS_ROUNDS
    entry = damage_entry(
        ability.get("name", "Spark Surge"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            amount=per_round,
            count=_E_LIGHTNING_ROUNDS_ROUNDS,
        ),
    )
    entry["detail"] = (
        f"{_E_LIGHTNING_ROUNDS_ROUNDS} Burst Fire rounds x {per_round:g} "
        f"bonus magic damage (crit multiplier {multiplier:.3f})"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["E"] = _spark_surge
parse_abilities = build_parser(SLOTS, "Zeri")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "E (Spark Surge) prices the dash plus Lightning Rounds: 7 Burst "
    "Fire rounds x the wiki's 'Burst Fire Bonus Magic Damage' row "
    "(22-30 + 20% AP, data/champions.json E), the E2-sourced round "
    "count on Q.",
    "Lightning Rounds bonus damage is 'increased by 0% : 100% (+ 0% : "
    "30%) (based on critical strike chance)'; the module scales "
    "linearly with crit chance, exact at the sourced 0%/100% endpoints.",
    "The dash itself deals no damage; 'Burst Fire Secondary Target "
    "Damage' (80-100%) applies to enemies past the first and is outside "
    "this single-target model.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

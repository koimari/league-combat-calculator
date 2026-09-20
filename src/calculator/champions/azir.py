"""Azir: slot map for the archetype engine.

W (Arise!) is the centrepiece.  One "Magic Damage" entry mixes an 18-value
per-level modifier with two 5-value per-rank ones, which no generic extractor
combines.  The soldier damage is an ``auto_attack_override`` that REPLACES
Azir's autos: magic on his own timer, cannot crit, applies on-hit and proc
item effects at 50% effectiveness except Sundered Sky, and +25% per soldier
past the first, those extras applying no on-hit.  W deals no cast damage, its
"Per-Level Scaling" row is the reduced damage to targets beyond the closest
and must never become a damage row, and its two charges make ``rechargeRate``
the cooldown.
Q (Conquering Sands) is one damage instance per cast whatever the soldier
count, so it must never read ``soldier_count``.
E (Shifting Sands) pins "Magic Damage" because the cache duplicates identical
values under "Shield Strength", which feeds the ally-support scanner instead.
R (Emperor's Divide) pins "Magic Damage"; its ``effects[0]`` geometry rows
carry units of " soldiers" and must never parse as damage or scaling.
P (Shurima's Legacy) raises a Sun Disc turret, a separate entity outside a
duel, and is wired nowhere: no leveling, and the parse emits no passive key.
"""

from typing import Any

from ..binary_roots import data_value, spell_object
from .charge_cadence import ChargeRule
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .inputs import bool_option, int_option
from .slot_extract import ability_name, extract_cooldown, extract_value
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# HARDCODED: wiki-prose soldier mechanics with no JSON home — verify on
# patch updates. https://wiki.leagueoflegends.com/en-us/Azir
_AZIR_W_SPELL = spell_object("Azir", "AzirW")
SOLDIER_EXTRA_DAMAGE = (
    data_value(_AZIR_W_SPELL, "SubsequentDamageMod") / 100.0
)  # each soldier past the first adds 25% damage
SOLDIER_ON_HIT_EFFECTIVENESS = data_value(
    _AZIR_W_SPELL, "OnHitMultiplier"
)  # on-hit items at 50% on soldier attacks


def _soldier_attack_damage(
    ability: dict[str, Any],
    rank: int,
    level: int,
    ability_power: float,
) -> float:
    """One Sand Soldier attack: per-level flat + per-rank base + AP ratio.

    All three are modifiers of the single "Magic Damage" leveling entry.
    """
    flat_level = extract_value(ability, "Magic Damage", level, modifier_index=0)
    rank_base = extract_value(ability, "Magic Damage", rank, modifier_index=1)
    ap_ratio = extract_value(ability, "Magic Damage", rank, modifier_index=2)
    return flat_level + rank_base + ap_ratio / 100.0 * ability_power


def _arise(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: zero-damage entry carrying the Sand Soldier auto replacement."""
    if not bool(ctx.option("soldier_autos")):
        return None  # Azir autos normally (physical, crits, full on-hit)
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_soldier = _soldier_attack_damage(
        ability, rank, ctx.level, ctx.stat("ability_power")
    )
    soldiers = max(1, int(ctx.option("soldier_count")))
    per_attack = per_soldier * (1.0 + SOLDIER_EXTRA_DAMAGE * (soldiers - 1))

    # Charge ability: rechargeRate is the sustained-use cooldown (the
    # JSON cooldown field holds only the 1.5s inter-cast timer).
    rates = ability.get("rechargeRate") or []
    cooldown = (
        float(rates[min(rank - 1, len(rates) - 1)])
        if rates
        else extract_cooldown(ability, rank)
    )

    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "magic",
        "total_raw": 0.0,  # all soldier damage rides the auto stream
        "parts": (),
        "detail": (f"Soldier attacks replace autos: {per_attack:.0f} magic per attack"),
        "auto_attack_override": {
            "name": "Sand Soldier Attacks",
            "replace_raw": per_attack,
            "damage_type": "magic",
            "on_hit_effectiveness": SOLDIER_ON_HIT_EFFECTIVENESS,
        },
    }


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "soldier_count",
        1,
        minimum=1,
        maximum=3,
        label="Sand Soldiers attacking the target",
        rotation={"role": "self_state", "slot": "R"},
    ),
    bool_option(
        "soldier_autos",
        True,
        label="Replace basic attacks with Sand Soldier attacks",
        rotation={"role": "self_state", "slot": "R"},
    ),
]

ASSUMPTIONS = [
    "Passive Sun Disc needs a destroyed tower, a separate entity: not modeled, "
    "no_damage rather than out_of_scope.",
    "Single-target: soldier spear line's reduced damage to targets beyond "
    "the closest (20-100% by level) not modeled",
    "Q deals one instance regardless of soldier count (in-game rule)",
    "E (Shifting Sands) shields Azir for 70/110/150/190/230 + 60% AP over 1.5s at the "
    "cast (cached Shield Strength row).",
    "E's ally-support packet is untimed, so the 1.5s expiry is a documented boundary "
    "of that interface.",
    "Soldier attacks take Azir's attack speed, cannot crit, carry no lifesteal, and "
    "apply on-hit at 50%.",
    "Additional soldiers' 25% instances apply no on-hit effects",
    "Every per-attack item effect (on-hit, spellblade, energized, Kraken-style procs) "
    "is 50% on soldier attacks.",
    "Sundered Sky does not apply to soldier attacks at all.",
]

SLOTS = {
    # Each of the three lands its damage once on a given target — Q states
    # it outright ("Enemies hit by subsequent soldiers take no additional
    # damage or slow"), E damages "enemies within his path" as it passes,
    # and R's phalanx impacts once — so all three certify the cast boundary.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": _arise,
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review.  Q slows enemies the soldiers pass through "by 25% for
# 1 second"; E only deals damage along the dash (its shield is Azir's own);
# R's phalanx knocks enemies "away over 1 second to a line 650 units in
# front of Azir".  W summons a soldier and emits no damage row of its own.
MODULE_CC = {"Q": "slow", "E": "none", "R": "knockback", "W": "none"}


# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "W": ChargeRule(
        why=(
            "W (Arise!) banks soldiers on its cached rechargeRate (6s "
            "at rank 5), which this slot already prices. The cached "
            "stock of 2 is not spent here: a soldier stays on the field "
            "and attacks, and no cached field states how many may stand "
            "at once, so spending the stock would summon soldiers the "
            "field cannot hold."
        ),
        charges=1,
    )
}
parse_abilities = build_parser(
    SLOTS, "Azir", cc_kinds=MODULE_CC, charge_rules=CHARGE_RULES
)


SOURCES = load_champion_sources("Azir")

# P is not absent for want of a parser: Sun Disc is a separate destroyed-tower
# entity that deals no enemy damage, which the derived map cannot say.
MODULE_COVERAGE = coverage(no_damage="P")

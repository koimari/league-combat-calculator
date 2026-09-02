"""Ahri — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Orb of Deception) deals its "Damage Per Pass" twice — magic
  outgoing, true returning: ``casts=2`` with the mixed split (half
  magic / half true) reproduces exactly one pass of each type.
- W (Fox-Fire) is three flames at two damage tiers: two DamageParts
  (initial + subsequent ``count=2``) so each flame mitigates separately.
- R (Spirit Rush) is three dashes per activation: one ``count=3`` part
  plus ``cast_instances=3`` (per-dash item procs), with no cooldown key
  so damage.py spaces the dashes itself.
- E (Charm) is a single, event-certified magic hit whose Wiki-authored
  charm/knockdown marker feeds conditional item triggers such as Fimbulwinter.
- P (Essence Theft) deals no enemy damage: the module emits a zero-damage
  receipt for the 9-fragment heal (35 : 95 by level + 20% AP, cached P
  "Heal" row) so the E1 self-heal rule can author one heal per fight when
  the user's fragment count has reached 9.  The champion-takedown heal
  (75 : 165 by level + 30% AP) is a kill boundary the fight model does not
  produce.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import champion_stat, int_option
from .module_contract import coverage
from .module_helpers import ranked_slot
from .slotlib import (
    ability_name,
    extract_auto,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
)
from .source_receipts import load_champion_sources


def _essence_theft(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: zero-damage receipt for the 9-fragment self-heal.

    Emitted only when the user's fragment count has reached 9 (the sourced
    stack cap in the cached P description); the E1 heal rule in healing.py
    gates its one-per-fight heal on this receipt.  The fragment count itself
    is player state (fragments come from minion/monster kills, which the
    champion duel does not simulate), so it is exposed as an option.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    fragments = max(0, int(ctx.option("p_essence_fragments")))
    if fragments < 9:
        return None
    return {
        "name": ability_name(ability),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            f"{fragments} Essence Fragment(s): at 9 stacks the passive heals "
            "35 : 95 (based on level) (+ 20% AP); the champion-takedown heal "
            "(75 : 165 by level + 30% AP) is a kill boundary, not a fight "
            "receipt."
        ),
    }


@ranked_slot
def _fox_fire(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: initial flame + 2 subsequent flames at reduced damage."""

    initial = extract_named(ability, "Primary Magic Damage", rank, ctx.stats)
    subsequent = extract_named(ability, "Subsequent Magic Damage", rank, ctx.stats)

    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "parts": (
            DamagePart("magic", initial),
            DamagePart("magic", subsequent, count=2),
        ),
        "total_raw": initial + (subsequent * 2),
        "damage_type": "magic",
    }


@ranked_slot
def _spirit_rush(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: three dashes emitted as one activation without a cooldown field."""
    per_cast, damage_type = extract_auto(ability, rank, ctx.stats, ctx.target)
    casts = 3
    return {
        "name": ability_name(ability),
        "rank": rank,
        "parts": (DamagePart(damage_type, per_cast, count=casts),),
        "cast_instances": casts,
        "total_raw": per_cast * casts,
        "damage_type": damage_type,
    }


@ranked_slot
def _charm(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """E: one magic hit with the authored charm/knockdown control marker."""
    damage = extract_auto(ability, rank, ctx.stats, ctx.target)[0]
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        # The charm's KIND is declared once in MODULE_CC and stamped onto
        # this part; what the entry states here is the sourced DURATION
        # and the separate claim that E's one hit lands at the cast
        # boundary, which is what puts the marker in the event ledger.
        "parts": (
            DamagePart(
                "magic",
                damage,
                cc_duration=extract_value(ability, "Disable Duration", rank),
            ),
        ),
        "total_raw": damage,
        "damage_type": "magic",
        "event_order_certified": "single_hit",
    }


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "p_essence_fragments",
        9,
        minimum=0,
        maximum=18,
        label="Essence Fragment stacks (9 = the passive heal is ready and "
        "consumes them)",
    ),
]

ASSUMPTIONS = [
    "P (Essence Theft) consumes 9 Essence Fragments to heal 35 : 95 "
    "(based on level) (+ 20% AP) — the cached P 'Heal' leveling row; "
    "fragment generation comes from minion/monster kills the 1v1 model "
    "does not simulate, so the user supplies the stack count "
    "(p_essence_fragments, default 9) and the heal fires once per fight "
    "on the first ability that hits the enemy champion",
    "The champion-takedown heal (75 : 165 by level + 30% AP) is a kill "
    "boundary — a takedown ends the fight before a heal receipt can apply",
]

SLOTS = {
    "P": _essence_theft,
    # One pass out and one back is one landing per enemy ("enemies can be
    # hit only once per pass"), split magic outgoing / true returning —
    # the mixed split ``engine._certify_shared_instant`` gives its shared
    # instant to.
    "Q": simple_damage(
        attr="Damage Per Pass",
        dmg_type="mixed",
        casts=2,
        event_order_certified="single_hit",
    ),
    "W": _fox_fire,
    "E": _charm,
    "R": _spirit_rush,
}

MODULE_COVERAGE = coverage(no_damage="P")

# Q (Orb of Deception) "deals magic damage to enemies it passes through"
# and returns "to deal the same amount in true damage" — damage only, so a
# reviewed absence of control.
#
# W and R stay UNREVIEWED, so this kit keeps the coarse control-armed
# scan.  Fox-Fire is two flame tiers (a second part of the same damage
# type, hitting twice) and Spirit Rush is three dashes in one part: both
# are schedules with unsourced cadence, which ``single_hit`` refuses.
MODULE_CC = {"E": "immobilize", "Q": "none"}


parse_abilities = build_parser(SLOTS, "Ahri", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Ahri")


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Ahri self-healing events from its authored packet."""
    healing = []
    if "passive" in ability_damages:
        # The module emits the P receipt only at 9+ fragments.
        level = int(champion_stat(champion_stats, "level"))
        heal = extract_named(
            _healing.ability_json(champion_data, "P"), "Heal", level, champion_stats
        )
        for event in damage_events:
            source = _healing.event_source(event)
            if source not in {"Q", "W", "E", "R"}:
                continue
            _healing.heal_from_damage(
                healing,
                event,
                heal,
                "Essence Theft",
                link_to_damage=False,
            )
            break
    return healing


SELF_HEALING_RULE = self_healing_rule("Ahri")(derive_self_healing)

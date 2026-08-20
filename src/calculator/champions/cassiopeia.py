"""Cassiopeia — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Noxious Blast) must read "Total Magic Damage" (the full 3s poison);
  the classifier picks the 7-tick "Magic Damage Per Tick" breakdown.
- W (Miasma) must read "Total Magic Damage" (the full 5s zone); the
  classifier picks "Magic Damage Per Second".
- E (Twin Fang) is champion-local: its unpoisoned base is a PER-LEVEL
  40-entry array (52 + 4/level, valid through the level-20 cap) plus
  10% AP, and the poisoned bonus is a separate rank-scaled leveling
  entry (20-120 + 55% AP) gated by the ``target_poisoned`` option. The
  JSON's pre-summed "Total Enhanced Damage" attribute is deliberately
  avoided — its level component carries only 18 values, so it cannot
  represent levels 19-20; the components are summed here instead.
- R (Petrifying Gaze) pins "Magic Damage" (the classifier happens to
  agree, but the module replaces the whole slot map).
- P (Serpentine Grace) is movement-speed only — deliberately absent.

Both of E's leveling entries are named "Bonus Magic Damage", so
``extract_named`` (first match wins) cannot reach the poisoned bonus —
``_bonus_magic_damage_levelings`` collects both in JSON order.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
    sum_modifiers,
)
from .source_receipts import load_champion_sources


def _bonus_magic_damage_levelings(
    ability: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """E's two "Bonus Magic Damage" entries: (per-level base, poisoned bonus).

    Raises IndexError if the JSON shape changes — a loud failure beats a
    silently unpoisoned Twin Fang.
    """
    matches = [
        leveling
        for effect in ability.get("effects", [])
        for leveling in effect.get("leveling", [])
        if leveling.get("attribute") == "Bonus Magic Damage"
    ]
    return matches[0], matches[1]


def _twin_fang(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: per-level base + 10% AP; poisoned targets add rank bonus + 55% AP."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    base_leveling, poison_leveling = _bonus_magic_damage_levelings(ability)
    # Base scales per champion LEVEL: modifier 0 is the 40-entry array
    # (indexed level-1), modifier 1 the 10% AP ratio.
    total = sum_modifiers(base_leveling, ctx.level, ctx.stats, ctx.target)
    if ctx.options.get("target_poisoned", True):
        # Poisoned: + rank-scaled bonus and +55% AP (65% AP total).
        total += sum_modifiers(poison_leveling, rank, ctx.stats, ctx.target)

    return damage_entry(
        ability.get("name", "Twin Fang"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        # One targeted launch, no travel or tick phase in the packet.
        event_order_certified="single_hit",
    )


# Q's poison ticks are the wiki packet's authored 0.429s cadence (seven
# over 3s); W's five ticks are the Total/Per-Second ratio (each tick is
# one second of the per-second row), which is the count the worklist
# sources.  Keeping the ticks explicit lets the coupled fight ledger
# order burns and incoming effects against Cassiopeia's damage instead
# of marking Q/W as aggregate cast-boundary damage.
_Q_TICKS = 7
_Q_FIRST_TICK = 0.429
_Q_TICK_INTERVAL = 0.429
_Q_DURATION = 3.0
_W_TICKS = 5
_W_DURATION = 5.0
_W_TICK_INTERVAL = _W_DURATION / _W_TICKS  # "every 1.0 seconds"


def _noxious_blast(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: full-poison total across seven sourced ticks (0.429s cadence).

    The "Total Magic Damage" row is read directly (75..215 at 0 AP) so
    the priced sum is exact at every rank; the per-tick row (10.71..30.71)
    is its rounded 1/7th, which would drift by ~0.03 per rank.  The seven
    ticks are still emitted as events for the coupled ledger.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Noxious Blast"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _Q_TICKS,
            count=_Q_TICKS,
            time_offset=_Q_FIRST_TICK,
            hit_interval=_Q_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _Q_DURATION
    entry["detail"] = "7 poison ticks at 0.429s intervals"
    return entry


def _miasma(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: full-zone total across five sourced per-second ticks.

    The "Total Magic Damage" row is exactly five times the "Magic Damage
    Per Second" row at every rank (100/20 .. 200/40), so the zone is
    priced as five per-second ticks over the five-second duration and
    the sum is exact.  (The wiki packet's raw 0.263s cadence would be
    19 x per-second/4 = 95% of the total — the round-off the worklist
    targets.)
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Miasma"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _W_TICKS,
            count=_W_TICKS,
            time_offset=_W_TICK_INTERVAL,
            hit_interval=_W_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _W_DURATION
    entry["detail"] = "5 per-second zone ticks over the 5s duration"
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "target_poisoned",
        "type": "bool",
        "default": True,
        "label": "Target poisoned (E enhanced damage)",
    },
]

ASSUMPTIONS = [
    "Target is poisoned for every Twin Fang cast (toggleable); in a real "
    "rotation Q/W keep poison up near-continuously",
    "W (Miasma) assumes the target remains in the zone for its full "
    "5-second duration",
    "E's healing against poisoned targets is not modeled (damage calculator)",
    "Passive (Serpentine Grace) is movement-speed only and not modeled",
    "R's facing condition does not change damage either way; for crowd "
    "control the duel's target is engaged with Cassiopeia and therefore "
    "facing her, so R's reviewed control is the stun branch ('Enemies "
    "with their facing direction towards her are instead stunned')",
]

SLOTS = {
    # Q/W poison ticks are ability damage past the cast, so item burns
    # (Liandry's, Blackfire) stay refreshed for the DoT tail
    # (dot_duration, like Brand's Blaze): Q poisons 3s, W ticks 5s.
    "Q": _noxious_blast,
    "W": _miasma,
    "E": _twin_fang,
    # One cone blast, no travel or tick phase in the packet.
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review.  Q's blast only poisons ("taking magic damage every
# 0.429 seconds"), W's clouds leave enemies "grounded and slowed" — a
# ground is not an immobilizing effect, the slow is the control — and E's
# fangs apply nothing at all.  R is left unreviewed: it slows enemies
# struck, and stuns "instead" those "with their facing direction towards
# her" — which the duel's target, engaged with Cassiopeia, is (see
# ASSUMPTIONS).
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "stun"}

parse_abilities = build_parser(SLOTS, "Cassiopeia", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Cassiopeia")

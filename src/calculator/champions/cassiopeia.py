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

from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, simple_damage, sum_modifiers


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
    )


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
    "R's stun/slow facing condition is not modeled (damage is identical either way)",
]

SLOTS = {
    # Q/W poison ticks are ability damage past the cast, so item burns
    # (Liandry's, Blackfire) stay refreshed for the DoT tail
    # (dot_duration, like Brand's Blaze): Q poisons 3s, W ticks 5s.
    "Q": simple_damage(attr="Total Magic Damage", dmg_type="magic", dot_duration=3.0),
    "W": simple_damage(attr="Total Magic Damage", dmg_type="magic", dot_duration=5.0),
    "E": _twin_fang,
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Cassiopeia")

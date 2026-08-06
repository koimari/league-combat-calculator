"""Shyvana's human/dragon combat states, self-shield, and timed packets.

E9-3: Inferno Aegis (W) now carries the sourced self-shield
('Shield Strength' + 12% bonus health, plus the per-nearby-champion
'Increased shield per champion' increment) as an E8c
``self_shield_events`` payload — the shield is granted at the cast and
consumed by the one-second recast.  The dragon-form recast heal
(60 : 104.71 by level + 4% : 8.47% by level missing health when the
explosion hits a champion) is authored by the healing rule in
``healing.py`` (HEALING_RULE_CHAMPIONS), keyed on the W recast damage
events and gated on the ``dragon_form`` option; the support scanner
defers both (see ``support_effects._MODULE_AUTHORED_SHIELD_SLOTS`` and
``_MODULE_AUTHORED_HEAL_SLOTS``)."""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)

# HARDCODED: verify on patch updates — the shield window and the recast
# window are prose in the cached W description ("shields herself for 2.5
# seconds" / "After 1 second, Inferno Aegis can be recast while the
# shield holds").  The shield amounts are cached leveling rows read live.
_W_SHIELD_DURATION_SECONDS = 2.5
_W_RECAST_WINDOW_SECONDS = 1.0


def _inferno_aegis_shield(ctx: SlotCtx) -> float:
    """W's self-shield: rank base + 12% bonus health, plus the sourced
    per-nearby-champion increment (a 1v1 duel is one nearby champion)."""
    ability = ctx.ability("W")
    if ability is None:
        return 0.0
    rank = ctx.rank_for("W")
    nearby = min(max(int(ctx.options.get("w_nearby_champions", 1)), 0), 5)
    base = extract_named(ability, "Shield Strength", rank, ctx.stats, ctx.target)
    per_champion = extract_named(
        ability, "Increased shield per champion", rank, ctx.stats, ctx.target
    )
    return base + nearby * per_champion


def _scalemail(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if ability is None:
        return None
    base = find_named_leveling(ability, "Per-Level Scaling", 0)
    stack = find_named_leveling(ability, "Per-Level Scaling", 1)
    if base is None or stack is None:
        return None
    stacks = min(max(int(ctx.options.get("scalemail_stacks", 0)), 0), 100)
    bonus_armor = sum_modifiers(base, ctx.level) + stacks * sum_modifiers(
        stack, ctx.level
    )
    ctx.stats["armor"] = ctx.stats.get("armor", 0.0) + bonus_armor
    ctx.stats["magic_resistance"] = ctx.stats.get("magic_resistance", 0.0) + bonus_armor
    entry = damage_entry("Scalemail", ctx.level, 0.0, 0.0, "physical")
    entry["stat_buff"] = {"armor": bonus_armor, "magic_resistance": bonus_armor}
    entry["detail"] = f"{stacks} Scalemail stack(s); +{bonus_armor:.2f} armor/MR"
    return entry


_scalemail.phase = BUFF


def _emberstrike(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    casts = min(max(int(ctx.options.get("q_casts", 1)), 1), 3)
    dragon = bool(ctx.options.get("dragon_form", False))
    human = extract_named(ability, "Area Physical Damage", rank, ctx.stats, ctx.target)
    dragon_third = extract_named(ability, "True Damage", rank, ctx.stats, ctx.target)
    parts: list[DamagePart] = []
    for index in range(casts):
        amount = dragon_third if dragon and index == 2 else human
        dtype = "true" if dragon and index == 2 else "physical"
        parts.append(DamagePart(dtype, amount, time_offset=0.0, hit_interval=0.0))
    total = sum(part.amount for part in parts)
    entry = damage_entry(
        ability.get("name", "Emberstrike"),
        rank,
        extract_cooldown(ability, rank),
        total,
        (
            "mixed"
            if len({part.damage_type for part in parts}) > 1
            else parts[0].damage_type
        ),
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{casts} Emberstrike cast(s), {'dragon' if dragon else 'human'} form"
    )
    entry["empowers_next_auto"] = True
    return entry


def _inferno_aegis(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the sourced self-shield plus the explosion damage.

    The shield is granted at the cast and consumed by the explosion: with
    w_recast=True (default) the player recasts after the sourced one-
    second window, with w_recast=False the shield holds its full 2.5-
    second window and the explosion fires automatically at expiry (wiki
    prose: "can be recast ... and does so automatically after it expires
    or is broken").  The E8c ``self_shield_events`` payload rides the
    explosion event (the ledger grants the timed shield at that event's
    timestamp — the module's sourced shield amount is the same either
    way).  The dragon-form explosion heal (60 : 104.71 by level + 4% :
    8.47% by level missing health when the explosion hits a champion) is
    authored by the healing rule in ``healing.py``, keyed on the W
    damage events and gated on the dragon-form marker in this detail.
    """
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    recast = bool(ctx.options.get("w_recast", True))
    dragon = bool(ctx.options.get("dragon_form", False))
    shield = _inferno_aegis_shield(ctx)
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    if recast:
        name = "Inferno Aegis (recast)"
        detail = (
            f"recast consumes the shield after the sourced "
            f"{_W_RECAST_WINDOW_SECONDS:g}-second window; the shield "
            f"({shield:g}) rides the explosion event"
        )
        detail += "; dragon form" if dragon else ""
        return attach_self_shield(
            damage_entry(
                name,
                rank,
                extract_cooldown(ability, rank),
                total,
                "magic",
            )
            | {
                "parts": (
                    DamagePart("magic", total, time_offset=_W_RECAST_WINDOW_SECONDS),
                )
            },
            amount=shield,
            duration=_W_RECAST_WINDOW_SECONDS,
            source="Inferno Aegis",
            detail=detail,
        )
    name = "Inferno Aegis"
    detail = (
        f"no recast: the shield ({shield:g}) holds its full "
        f"{_W_SHIELD_DURATION_SECONDS:g}-second window and the "
        f"auto-explosion fires at expiry (+{_W_SHIELD_DURATION_SECONDS:g}s)"
    )
    detail += "; dragon form" if dragon else ""
    return attach_self_shield(
        damage_entry(
            name,
            rank,
            extract_cooldown(ability, rank),
            total,
            "magic",
        )
        | {
            "parts": (
                DamagePart("magic", total, time_offset=_W_SHIELD_DURATION_SECONDS),
            )
        },
        amount=shield,
        duration=_W_SHIELD_DURATION_SECONDS,
        source="Inferno Aegis",
        detail=detail,
    )


def _molten_burst(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    dragon = bool(ctx.options.get("dragon_form", False))
    attr = "Increased/Explosion Magic Damage" if dragon else "Magic Damage"
    total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    parts = [DamagePart("magic", total, time_offset=0.0)]
    if dragon and bool(ctx.options.get("e_second_explosion", False)):
        second = extract_named(
            ability, "Subsequent Explosion Damage", rank, ctx.stats, ctx.target
        )
        parts.append(DamagePart("magic", second, time_offset=0.0))
        total += second
    entry = damage_entry(
        ability.get("name", "Molten Burst"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = "dragon-form explosion" if dragon else "human-form fireball"
    return entry


SLOTS = {
    "P": _scalemail,
    "Q": _emberstrike,
    "W": _inferno_aegis,
    "E": _molten_burst,
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Shyvana")

OPTIONS = [
    {
        "key": "scalemail_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 100,
        "label": "Scalemail stacks",
    },
    {"key": "dragon_form", "type": "bool", "default": False, "label": "Dragon Form"},
    {
        "key": "q_casts",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 3,
        "label": "Emberstrike casts",
    },
    {
        "key": "w_recast",
        "type": "bool",
        "default": True,
        "label": "Inferno Aegis recast hits",
    },
    {
        "key": "w_nearby_champions",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 5,
        "label": "Nearby enemy champions (W shield increment)",
    },
    {
        "key": "e_second_explosion",
        "type": "bool",
        "default": False,
        "label": "Dragon E second explosion",
    },
]

ASSUMPTIONS = [
    "Scalemail armor and magic resistance use explicit stack state; the "
    "passive has no direct damage.",
    "Inferno Aegis grants the sourced self-shield ('Shield Strength' 60-140 "
    "by rank + 12% bonus health, plus 'Increased shield per champion' "
    "18-42 by rank + 3.6% bonus health per nearby enemy champion, "
    "w_nearby_champions default 1 for a 1v1) for 2.5s, or until the "
    "one-second recast consumes it.",
    "The dragon-form recast heal (60 : 104.71 based on level + 4% : 8.47% "
    "based on level of missing health when the explosion hits a champion) "
    "is authored by the healing rule (healing.py, HEALING_RULE_CHAMPIONS) "
    "keyed on the W recast damage events and gated on dragon_form; the "
    "human-form recast deals the sourced damage without healing.",
    "Inferno Aegis defaults to its one-second recast damage; with "
    "w_recast=False the shield holds its full 2.5-second window and the "
    "auto-explosion at expiry is not priced.",
    "Dragon-form Q/E variants and the second explosion are explicit "
    "options, never inferred from a cast count.",
]

SOURCES = [
    {
        "label": "Shyvana — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Shyvana",
        "revision_id": 4043672,
        "revision_timestamp": "2026-07-15T18:06:00Z",
    }
]

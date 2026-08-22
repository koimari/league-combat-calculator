"""Gragas' charge-scaled barrel and empowered brew attack."""

from __future__ import annotations

import re
from typing import Any

from ..ability_spec import DamagePart
from .inputs import bool_option, champion_stat
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .module_helpers import no_damage
from .slotlib import ability_name, damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources
from ..healing_helpers import ability_json


def _happy_hour(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Happy Hour",
        reason="5.5% maximum-health heal after casting; no outgoing damage.",
        slot="P",
    )


def _barrel_roll(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    charged = bool(ctx.option("q_fully_fermented"))
    attr = "Maximum Magic Damage" if charged else "Minimum Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=2.0),)
    entry["detail"] = (
        f"{('Fully' if charged else 'minimum')} fermented barrel; source slow scales with the same charge state."
    )
    return entry


def _drunken_rage(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["empowers_next_auto"] = True
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "One brew-empowered basic attack; max-health term is evaluated against the live target."
    )
    entry["target_max_health_sensitive"] = True
    return entry


def _body_slam(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "Collision damage plus sourced knockback/stun; cooldown refund is not assumed without a hit state."
    )
    return entry


def _explosive_cask(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.5),)
    return entry


SLOTS = {
    "P": _happy_hour,
    "Q": _barrel_roll,
    "W": _drunken_rage,
    "E": _body_slam,
    "R": _explosive_cask,
}
# Q's cask detonation "slow[s] them for 2 seconds"; W only empowers an
# attack; E and R each lead with a displacement ("knocking them back") on
# the enemies they damage, so each declares its first-listed immobilize.
# P is the self-heal and authors no damage part.
MODULE_CC = {"Q": "slow", "W": "none", "E": "knockback", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Gragas", cc_kinds=MODULE_CC)

OPTIONS = [
    bool_option("q_fully_fermented", True, label="Barrel Roll fully fermented"),
]

ASSUMPTIONS = [
    "Barrel Roll exposes the minimum and fully fermented maximum damage branches; the source charge timing is not averaged.",
    "Drunken Rage is a single empowered attack with a target-max-health rider; the channel damage reduction is defensive state.",
    "Body Slam's cooldown refund requires a collision state and is not applied to every cast by default.",
]

SOURCES = load_champion_sources("Gragas")


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Happy Hour pays 5.5% of maximum health on each ability CAST.

    Cached Wiki text: "Periodically, after casting an ability, Gragas heals
    himself for 5.5% of his maximum health".  The heal triggers on the
    cast, not on damage landing, so the cast timeline is the occasion; one
    cast pays one self-heal (actor-wide receipt).
    """
    healing: list[dict] = []
    p_text = " ".join(
        effect.get("description", "")
        for effect in ability_json(champion_data, "P").get("effects", [])
    )
    ratio_match = re.search(
        r"heals himself for\s+(\d+(?:\.\d+)?)%\s+of his maximum health",
        p_text,
        flags=re.IGNORECASE,
    )
    ratio = float(ratio_match.group(1)) / 100.0 if ratio_match else 0.0
    per_cast = ratio * champion_stat(champion_stats, "health")
    if per_cast > 0.0:
        for cast in cast_timeline or []:
            slot = cast.get("slot")
            if slot not in {"Q", "W", "E", "R"}:
                continue
            healing.append(
                {
                    "time": float(cast.get("time", 0.0)),
                    "amount": per_cast,
                    "source": f"Happy Hour · {slot}",
                    "kind": "champion_passive",
                    "actor_wide": True,
                }
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Gragas")(derive_self_healing)

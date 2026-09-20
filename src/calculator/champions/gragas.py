"""Gragas' charge-scaled barrel and empowered brew attack."""

from __future__ import annotations

import re
from typing import Any

from ..ability_prose import CachedSentence
from ..ability_spec import DamagePart
from ..healing_helpers import ability_json
from .engine import SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option, champion_stat
from .module_helpers import named_damage, no_damage_slot, ranked_slot
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .source_receipts import load_champion_sources

# Happy Hour is prose only: no P leveling row carries the share of maximum
# health one cast pays back.
_HAPPY_HOUR_SHARE = CachedSentence(
    re.compile(
        r"heals himself for\s+(?P<value>\d+(?:\.\d+)?)%\s+of his maximum health",
        re.IGNORECASE,
    ),
    missing=(
        "Gragas P (Happy Hour): the cached innate no longer states the "
        "self-heal share ('heals himself for N% of his maximum health')"
    ),
)


_happy_hour = no_damage_slot(
    "5.5% maximum-health heal after casting; no outgoing damage.",
    name="Happy Hour",
)


@ranked_slot
def _barrel_roll(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
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
        f"{('Fully' if charged else 'minimum')} fermented barrel; source slow scales "
        f"with the same charge state."
    )
    return entry


_drunken_rage = named_damage(
    "Bonus Magic Damage",
    "magic",
    empowers_next_auto=True,
    event_order_certified="single_hit",
    detail="One brew-empowered basic attack; max-health term is evaluated against the live target.",
    target_max_health_sensitive=True,
)


_body_slam = named_damage(
    "Magic Damage",
    "magic",
    event_order_certified="single_hit",
    detail="Collision damage plus sourced knockback/stun; cooldown refund is not assumed "
    "without a hit state.",
)


_explosive_cask = named_damage(
    "Magic Damage",
    "magic",
    time_offset=0.5,
)


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
MODULE_CC = {"Q": "slow", "W": "none", "E": "knockback", "R": "knockback", "P": "none"}

parse_abilities = build_parser(SLOTS, "Gragas", cc_kinds=MODULE_CC)

OPTIONS = [
    bool_option("q_fully_fermented", True, label="Barrel Roll fully fermented"),
]

ASSUMPTIONS = [
    "Barrel Roll exposes the minimum and fully fermented maximum damage branches; the "
    "source charge timing is not averaged.",
    "Drunken Rage is a single empowered attack with a target-max-health rider; the "
    "channel damage reduction is defensive state.",
    "Body Slam's cooldown refund requires a collision state and is not applied to "
    "every cast by default.",
]

SOURCES = load_champion_sources("Gragas")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Happy Hour pays 5.5% of maximum health on each ability CAST.

    Cached Wiki text: "Periodically, after casting an ability, Gragas heals
    himself for 5.5% of his maximum health".  The heal triggers on the
    cast, not on damage landing, so the cast timeline is the occasion; one
    cast pays one self-heal (actor-wide receipt).
    """
    healing: list[dict] = []
    ratio = _HAPPY_HOUR_SHARE.value(ability_json(ctx.champion_data, "P")) / 100.0
    per_cast = ratio * champion_stat(ctx.champion_stats, "health")
    if per_cast > 0.0:
        for cast in ctx.cast_timeline or []:
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

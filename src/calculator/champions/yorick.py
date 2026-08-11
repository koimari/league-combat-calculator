"""Yorick — Mist Walkers and the Maiden of the Mist (E4 summon damage).

Why each slot is non-generic:
- P (Shepherd of Souls) raises Mist Walkers (up to 4 active).  The pet
  attack damage is NOT in the champion JSON (its leveling rows are
  empty and the ability text points to "See Pets for more details"), so
  the per-attack damage is a module constant sourced from the Community
  Dragon game files (see the HARDCODED block below) and emitted as a
  fixed-count proc over the fight window: ``mist_walkers`` x
  ``mist_walker_attacks`` attacks.
- R (Eulogy of the Isles) summons the Maiden of the Mist, a controllable
  pet whose attack damage also lives only in the game files.  The R slot
  keeps its castable row and prices ``maiden_attacks`` basic attacks
  over the fight window (AS 1.0 -> 5 attacks in the 5-second
  one-rotation window by default).
- Q/W/E keep the reviewed CP10.10 packet pricing (W is a zero-damage
  wall, E keeps its sourced % max-health magic damage).

Pet damage boundaries: the fight model does not price pet HP, leash
ranges, or AI; the walkers and the Maiden are assumed to reach and keep
attacking the target for the whole window.  The attack counts are
player-controlled options whose defaults follow the sourced attack
pattern over the 5-second one-rotation window.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from ..stats import growth_multiplier
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown

PACKET_SHA256 = "906b7a57f67c65c1729d75e139e3608eaf8532c564638f0f008b2b1f7348c8f5"

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module("Yorick", PACKET_SHA256)
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec

# HARDCODED: verify on patch updates — pet stats are not scraped into
# data/champions.json (the ability text points to "See Pets for more
# details").  Sourced from the Community Dragon game files (current
# patch; the wiki pet infobox on the fandom mirror is stale — it still
# lists the Maiden at 0/10/40 + 50% AD while the game file says
# 50/75/100 + 30% bonus AD; the 13.21 patch moved the rank bases):
#   https://raw.communitydragon.org/latest/game/data/characters/
#     yorick/yorick.bin.json  (YorickPassive / YorickR spell calcs)
#     yorickghoulmelee/yorickghoulmelee.bin.json  (Mist Walker unit)
#     yorickbigghoul/yorickbigghoul.bin.json      (Maiden unit)
# Mist Walker attack: YorickPassiveGhoulDamage = 15 : 100 (based on
# level; by-char-level interpolation scaled by the stat progression
# multiplier — exactly 100 at level 18) (+ 20% AD, GhoulADRatio),
# physical.  Attack speed 0.5 : 1.18 (based on level, wiki) -> 5
# attacks in the 5s window at level 18.
# Maiden attack: YorickBigGhoulDamage = RBigGhoulBonusAD
# (50/100/150 at R rank 1/2/3) (+ 30% AD, MaidenADRatio), magic.
# Attack speed 1.0 -> 5 attacks in the 5s window.
_MIST_WALKER_DAMAGE_START = 15.0  # level 1
_MIST_WALKER_DAMAGE_END = 100.0  # level 18
# Pet AD ratios price BONUS AD, not total AD (autoresearch pass 35): the
# game files / wiki patch history pin Mist Walker at 20% bonus AD and the
# Maiden at 30% bonus AD; the Maiden rank base is 50/75/100 (13.21 change).
_MIST_WALKER_AD_RATIO = 0.20
_MIST_WALKER_MAX = 4
_MIST_WALKER_AS_AT_18 = 1.18
_MAIDEN_BASE_BY_RANK = (50.0, 75.0, 100.0)
_MAIDEN_AD_RATIO = 0.30
_MAIDEN_AS = 1.0


def _mist_walker_attack_damage(ctx: SlotCtx) -> float:
    """One Mist Walker basic attack at the champion's level.

    The game-file interpolation (15 at level 1 -> 100 at level 18) is
    scaled by the standard stat progression multiplier (1.0 at level
    18), then the sourced 20% AD ratio applies.
    """
    span = _MIST_WALKER_DAMAGE_END - _MIST_WALKER_DAMAGE_START
    interpolated = _MIST_WALKER_DAMAGE_START + span * (ctx.level - 1) / 17.0
    base = interpolated * growth_multiplier(ctx.level)
    return base + _MIST_WALKER_AD_RATIO * ctx.stats.get("bonus_attack_damage", 0.0)


def _mist_walkers(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Mist Walkers — fixed-count proc over the fight window."""
    ability = ctx.ability()
    if ability is None:
        return None
    walkers = min(max(int(ctx.options.get("mist_walkers", _MIST_WALKER_MAX)), 0), 4)
    attacks = min(max(int(ctx.options.get("mist_walker_attacks", 5)), 0), 12)
    count = walkers * attacks
    if count <= 0:
        return no_damage(
            ctx,
            name="Mist Walkers",
            reason=(
                f"{walkers} Mist Walker(s) x {attacks} attacks per walker in the "
                "window — set mist_walkers / mist_walker_attacks to price them."
            ),
        )
    per = _mist_walker_attack_damage(ctx)
    entry: dict[str, Any] = {
        "name": "Mist Walkers",
        "damage_type": "physical",
        "total_raw": per * count,
        "parts": (DamagePart("physical", per),),
        "proc_count": count,
        "event_phase": "effect",
        "damage_events": [
            {
                "time": 0.0,
                "damage_type": "physical",
                "damage": per,
                "event_precision": "phase_order",
            }
            for _ in range(count)
        ],
        "detail": (
            f"{walkers} Mist Walker(s) x {attacks} attacks = {count} attacks of "
            f"{per:.2f} physical (15 : 100 based on level x stat progression + "
            "20% AD); attacks spread over the fight window, pet pathing not modeled"
        ),
    }
    return entry


def _maiden(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Eulogy of the Isles — Maiden basic attacks over the window."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attacks = min(max(int(ctx.options.get("maiden_attacks", 5)), 0), 10)
    if attacks <= 0:
        return no_damage(
            ctx,
            name="Maiden of the Mist",
            reason="maiden_attacks is 0 — set it to price Maiden basic attacks.",
        )
    base = _MAIDEN_BASE_BY_RANK[min(rank - 1, len(_MAIDEN_BASE_BY_RANK) - 1)]
    per = base + _MAIDEN_AD_RATIO * ctx.stats.get("bonus_attack_damage", 0.0)
    entry = damage_entry(
        ability.get("name", "Eulogy of the Isles"),
        rank,
        extract_cooldown(ability, rank),
        per * attacks,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per, count=attacks, time_offset=0.0, hit_interval=1.0),
    )
    entry["detail"] = (
        f"Maiden of the Mist: {attacks} basic attacks of {per:.2f} magic "
        f"({base:.0f} at R rank {rank} + 30% AD) at 1.0 attack speed; the "
        "Touch of the Maiden mark is not modeled"
    )
    return entry


OPTIONS = [
    {
        "key": "mist_walkers",
        "type": "int",
        "default": 4,
        "label": "Mist Walkers attacking the target",
        "min": 0,
        "max": 4,
    },
    {
        "key": "mist_walker_attacks",
        "type": "int",
        "default": 5,
        "label": "Mist Walker attacks per walker (5s window)",
        "min": 0,
        "max": 12,
    },
    {
        "key": "maiden_attacks",
        "type": "int",
        "default": 5,
        "label": "Maiden of the Mist attacks (5s window)",
        "min": 0,
        "max": 10,
    },
]

ASSUMPTIONS = [
    "Every slot is an explicit packet or sourced no-damage entry from the "
    "pinned local Wiki cache; no runtime archetype inference is used.",
    "Numeric packets preserve rank/level arrays, typed scaling, target-health "
    "terms, and explicit variant selectors where the source lists them.",
    "The complete parent Wiki entry was read before certifying this module.",
    "Passive plus Q/W/E/R entries are represented by explicit packet or "
    "no-damage slot declarations.",
    "Rank arrays, cooldowns, typed target-health terms, and packet variants "
    "remain sourced from the local reviewed-packet asset.",
    "Non-damaging shields, buffs, movement, and utility branches remain "
    "explicit state/out-of-scope rows rather than invented damage.",
    "Mist Walker attack damage (15 : 100 by level x stat progression + 20% ",
    "bonus AD, physical) and Maiden attack damage (50/75/100 by R rank + 30% ",
    "bonus AD, magic — 13.21 rank bases)",
    "are game-file constants — the wiki pet infobox is stale; verify on patch ",
    "updates against Community Dragon",
    "Mist Walkers attack at 0.5 : 1.18 attack speed (based on level): the ",
    "default 5 attacks per walker fills the 5-second one-rotation window; pet ",
    "pathing, HP and leash range are not modeled",
    "Maiden attacks at 1.0 attack speed (default 5 attacks per window); the ",
    "Touch of the Maiden % max-health mark and recast-lane-push are state, not ",
    "modeled",
    "The 30% bonus damage Mist Walkers deal against Mourning Mist-marked ",
    "enemies for 8 attacks is not modeled (mark state)",
]
SLOTS = {
    "P": _mist_walkers,
    "Q": _BATCH_SLOTS["Q"],
    "W": _BATCH_SLOTS["W"],
    "E": _BATCH_SLOTS["E"],
    "R": _maiden,
}

parse_abilities = build_parser(SLOTS, "Yorick")
SOURCES = _BATCH_SOURCES
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Yorick self-healing events from its authored packet."""
    healing = []
    q = _healing._ability(champion_data, "Q")
    q_rank = _healing._rank(ability_damages, "Q")
    q_level = int(champion_stats.get("level", 0) or 0)
    q_flat = _healing._leveling_flat_at_level(q, "Heal", q_level)
    q_missing_ratio = (
        _healing._leveling_ratio(q, "Heal", "missing health", q_rank) / 100.0
    )

    def last_rites_heal(
        current_health: float,
        maximum_health: float,
        flat: float = q_flat,
        missing_ratio: float = q_missing_ratio,
    ) -> float:
        return flat + max(0.0, maximum_health - current_health) * missing_ratio

    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "Q"
    ):
        healing.append(
            {
                "time": float(event.get("time", 0.0)),
                "amount": 0.0,
                "amount_formula": last_rites_heal,
                "source": "Last Rites",
                "kind": "champion_ability",
                **_healing._trigger_fields(event),
            }
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Yorick", derive_self_healing)

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
- Q/W/E keep the reviewed CP10.10 packet pricing (E keeps its sourced
  % max-health magic damage).  W (Dark Procession) stays out of scope:
  its ring is impassable terrain with its own wall health, an axis the
  engine does not have, and it deals nothing.

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
from .engine import SlotCtx
from .healing_contract import declare_healing_rule
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown

PACKET_SHA256 = "906b7a57f67c65c1729d75e139e3608eaf8532c564638f0f008b2b1f7348c8f5"


# HARDCODED: verify on patch updates — pet stats are not scraped into
# data/champions.json (the ability text points to "See Pets for more
# details").  Sourced from the Community Dragon game files (current
# patch; the wiki pet infobox on the fandom mirror is stale — it still
# lists the Maiden at 0/10/40 + 50% AD while the game file says
# 50/100/150 + 30% AD):
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
    return base + _MIST_WALKER_AD_RATIO * ctx.stat("bonus_attack_damage")


def _mist_walkers(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Mist Walkers — fixed-count proc over the fight window."""
    ability = ctx.ability()
    if ability is None:
        return None
    walkers = min(max(int(ctx.options.get("mist_walkers", _MIST_WALKER_MAX)), 0), 4)
    attacks = min(max(int(ctx.option("mist_walker_attacks")), 0), 12)
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
    attacks = min(max(int(ctx.option("maiden_attacks")), 0), 10)
    if attacks <= 0:
        return no_damage(
            ctx,
            name="Maiden of the Mist",
            reason="maiden_attacks is 0 — set it to price Maiden basic attacks.",
        )
    base = _MAIDEN_BASE_BY_RANK[min(rank - 1, len(_MAIDEN_BASE_BY_RANK) - 1)]
    per = base + _MAIDEN_AD_RATIO * ctx.stat("bonus_attack_damage")
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


# Mourning Mist's globule lands and "enemy champions and monsters hit are
# slowed by 30% for 1.5 seconds"; Last Rites' empowered swing only damages
# and heals, and the R row prices the Maiden's basic attacks, which control
# nothing.  W (Dark Procession) is where the knock-aside and the pull live,
# but the ring deals no damage.  P is the Mist Walker pet row, not an
# ability event.
MODULE_CC = {"Q": "none", "E": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yorick",
    PACKET_SHA256,
    assumption_overrides=(
        "Mist Walker attack damage (15 : 100 by level x stat progression + 20% AD, physical) and "
        "Maiden attack damage (50/100/150 by R rank + 30% AD, magic) are game-file constants — the "
        "wiki pet infobox is stale; verify on patch updates against Community Dragon",
        "Mist Walkers attack at 0.5 : 1.18 attack speed (based on level): the default 5 attacks "
        "per walker fills the 5-second one-rotation window; pet pathing, HP and leash range are "
        "not modeled",
        "Maiden attacks at 1.0 attack speed (default 5 attacks per window); the Touch of the "
        "Maiden % max-health mark and recast-lane-push are state, not modeled",
        "The 30% bonus damage Mist Walkers deal against Mourning Mist-marked enemies for 8 attacks "
        "is not modeled (mark state)",
    ),
    # Q is one empowered swing and E is one globule's splash; neither
    # has a travel or tick phase to place.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "P": _mist_walkers,
        "R": _maiden,
    },
    slot_order=("P", "Q", "W", "E", "R"),
    cc_kinds=MODULE_CC,
)

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


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}

SELF_HEALING_RULE = declare_healing_rule("Yorick")

"""Teemo — CP10.8 full-entry-reviewed packet module.

E9-1 closes the last audit gap: E (Toxic Shot) now prices the on-hit
PLUS the full 4-second poison DoT.  The packet priced only the
"Magic Damage On-Hit" row; the cached JSON's "Magic Damage per Tick"
(6-30 + 2.5% bonus AD + 10% AP) and "Total Poison Damage"
(24-120 + 10% bonus AD + 40% AP) rows are now expressed as 4 ticks at
1-second intervals (this module's packet timing declaration).

E4 summon: R (Noxious Trap) is a summoned trap.  The E2-3 tick fix
already prices one shroom detonation as the full 4-second poison (4
ticks of "Magic Damage per Tick" == the wiki Total Magic Damage row at
every rank, one tick per second).  This module keeps that pricing and
adds the player-controlled trap state:

- ``r_shrooms`` (default 1) — how many shroom detonations the fight
  prices.  The wiki note is explicit that stepping on multiple shrooms
  only REFRESHES the poison duration (never stacks), so each detonation
  prices its own full 4-tick DoT; a cluster walked onto simultaneously
  would be one DoT, and ``r_shrooms`` models sequential detonations
  (pre-placed field, charges stocked every 35/30/25s by rank).
- The sourced slow (30/40/50% by rank for 4 seconds, from the cache's
  "Slow" leveling row) is crowd-control utility the fight model does
  not price; it is reported on the row detail.

Boundary: shroom/trap placement, arm time, trigger radius and the 6-HP
trap health bar are state the fight model does not price — the damage
is the detonation DoT above.

Coverage: W (Move Quick) is Teemo's own movement speed with no
enemy-damage clause anywhere in the slot, so it is a zero-damage row
carrying the cast's sourced ``move_speed_percent`` stat buff.  P
(Guerrilla Warfare) is idle stealth
with a real attack-speed steroid on breaking it, which WOULD change
damage — so it stays ``out_of_scope`` with a receipt (the Olaf-R rule),
never ``no_damage``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..binary_roots import data_value, spell_object
from .engine import SlotCtx
from .module_contract import coverage
from .module_helpers import buff_window_share, with_detail
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import extract_value

# Sourced cadence for one Noxious Trap detonation (cache + wiki):
# "the target takes magic damage every second over 4 seconds" — 4 ticks
# at 1s; per-tick x4 == the wiki Total Magic Damage row.
_TEEMO_R_SPELL = spell_object("Teemo", "TeemoR")
_R_TICKS = 4
_R_TICK_INTERVAL = 1.0
_R_DOT_SECONDS = data_value(_TEEMO_R_SPELL, "DebuffDuration")


def _shroom_detonations(ctx: SlotCtx) -> int:
    """Clamped ``r_shrooms``: shrooms detonating during the fight.

    R stocks up to 3/4/5 charges by rank (the "Maximum Charges" row);
    the player controls how many pre-placed shrooms the enemy walks
    onto.  Sequential detonations each price a full poison DoT.
    """
    ability = ctx.ability()
    rank = ctx.rank_for()
    cap = 5
    if ability is not None and rank >= 1:
        cap = max(1, int(extract_value(ability, "Maximum Charges", rank) or 5))
    return min(max(int(ctx.option("r_shrooms")), 1), cap)


def _noxious_trap(packet_r):
    """R: one full poison DoT per shroom detonation (E2-3 tick pricing)."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_r(ctx)
        if entry is None:
            return None
        shrooms = _shroom_detonations(ctx)
        if shrooms > 1:
            entry["parts"] = tuple(
                dataclasses.replace(part, count=part.count * shrooms)
                for part in entry["parts"]
            )
            entry["total_raw"] = entry.get("total_raw", 0.0) * shrooms
        slow = 0.0
        ability = ctx.ability()
        rank = ctx.rank_for()
        if ability is not None and rank >= 1:
            slow = extract_value(ability, "Slow", rank)
        inherited = entry.get("detail", "")
        entry["detail"] = (
            f"{shrooms} shroom detonation(s), each poisoning for "
            f"{_R_DOT_SECONDS:g}s ({_R_TICKS} ticks at {_R_TICK_INTERVAL:g}s "
            f"intervals) and slowing {slow:g}% for 4s."
            + (f" {inherited}" if inherited else "")
        )
        return entry

    return parse


PACKET_SHA256 = "82f4b06f86d7d9d576a27f3e9e4e639261e0bb5f50c969cd0592a0ff8459a2f4"

# HARDCODED: verify on patch updates — the Udyr-E / Singed-R precedent, a
# window that is cached PROSE rather than an atom.  W's ACTIVE doubles the
# grant "for 3 seconds" by the second effect's description.  The slot's one
# ``timing.active_duration`` atom reads 5.0 and must NOT be used: it is the
# FIRST effect's passive condition ("after 5 seconds without taking ...
# damage"), an idle requirement rather than the cast's window.
_W_ACTIVE_SECONDS = data_value(
    spell_object("Teemo", "TeemoW"), "ActiveMoveSpeedBuffDuration"
)


def _move_quick(packet_w):
    """W: movement only — a sourced zero-enemy-damage row.

    Replaces the packet's generic "no enemy-damage formula" stub with the
    sourced movement numbers, and publishes the cast's own grant as a
    ``move_speed_percent`` stat buff.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_w(ctx)
        if entry is None:
            return None
        ability = ctx.ability()
        rank = ctx.rank_for()
        if ability is None or rank < 1:
            return entry
        passive_ms = extract_value(ability, "Bonus Movement Speed", rank)
        active_ms = extract_value(ability, "Enhanced Bonus Movement Speed", rank)
        # The ACTIVE's row, because the passive's own condition ("after 5
        # seconds without taking damage from enemy champions") is one a
        # fight never satisfies.  It rides the cast like every other
        # steroid the engine prices, so a rotation that never casts W
        # earns none of it.
        # The cast expires, and a stat_buff is one scalar for the whole
        # fight, so the grant lands time-weighted by the share of the
        # window it covers (module_helpers.buff_window_share).
        published_ms = active_ms * buff_window_share(ctx, _W_ACTIVE_SECONDS)
        entry["stat_buff"] = {"move_speed_percent": published_ms}
        entry["detail"] = (
            f"Movement only: {passive_ms:g}% bonus movement speed after 5s "
            f"undamaged, doubled to {active_ms:g}% for "
            f"{_W_ACTIVE_SECONDS:g}s on cast ({published_ms:g}% over the "
            "fight window). The cast's grant is published as a "
            "move_speed_percent stat buff, which is a term in the shared "
            "movement-speed fold."
        )
        return entry

    return parse


# P: stealth + a real but unmodelable attack-speed steroid.  Kept
# ``out_of_scope`` (receipted open, the Olaf-R rule) because Element of
# Surprise WOULD change damage if it could be modeled.  The row states the
# mechanic and the two live blockers instead of pretending the slot is
# non-damaging.
_guerrilla_warfare = with_detail(
    "Stealth (utility) plus Element of Surprise: 20% / 40% / 60% / "
    "80% (based on level) bonus attack speed for 5s on breaking "
    "stealth. Not modeled and not called no_damage. (1) The trigger "
    "is unreachable: the cached innate grants the stealth only "
    "'after 1.5 seconds without moving, taking non-over-time "
    "damage, performing actions that break stealth' — a state a "
    "modeled fight never enters, which is what separates this from "
    "Twitch Q, an active cast the rotation does break. (2) The "
    "magnitude has no cached ability atom: both P effect rows carry "
    "an empty leveling array, so the ladder exists only as wiki "
    "prose plus the binary's TeemoPassive BonusAttackSpeed level "
    "breakpoints (0.20 at level 1, +0.20 at 5/10/15) and would have "
    "to be republished as a module constant with no cached "
    "accessor behind it."
)


# Reviewed crowd control, read from the cached kit.  Q (Blinding Dart)
# "deals magic damage and blinds them for a duration" — real crowd
# control that is neither an immobilize nor a movement slow, which is
# what ``blind`` is in ability_spec.CC_KIND_VOCABULARY.  E (Toxic Shot)
# is an on-hit poison — "the target takes magic damage every second over
# 4 seconds" — with no control clause.  R (Noxious Trap) detonates
# "inflicting poison to nearby enemies and slowing them for 4 seconds".
# W (Move Quick) is Teemo's own movement speed and authors no damage.
MODULE_CC = {"Q": "blind", "E": "none", "R": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Teemo",
    PACKET_SHA256,
    # Blinding Dart is one dart "at the target enemy" — one part and one
    # hit, which is what carries Q's reviewed blind into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    assumption_overrides=(
        "Noxious Trap prices the full 4-second poison: 4 ticks of Magic "
        "Damage per Tick (== Total Magic Damage) at 1-second intervals.",
    ),
    packet_tick_fixes={
        "Toxic Shot": {
            "initial_tick": 0.0,
            "extra_part": {
                "attribute": "Magic Damage per Tick",
                "count": 4,
                "damage_type": "magic",
                "first_tick": 1.0,
                "tick_interval": 1.0,
                "dot_duration": 4.0,
            },
        }
    },
    slot_parsers={
        "R": repeat_damage_parser(
            attr="Magic Damage per Tick",
            dmg_type="magic",
            count=4,
            time_offset=1.0,
            hit_interval=1.0,
            dot_duration=4.0,
        )
    },
    slot_wrappers={
        "R": _noxious_trap,
        "W": _move_quick,
        "P": _guerrilla_warfare,
    },
    cc_kinds=MODULE_CC,
)
ASSUMPTIONS.extend(
    [
        "R (Noxious Trap) is a summoned trap: one detonation prices the "
        "full 4-second poison DoT (E2-3 ticks); r_shrooms prices "
        "sequential detonations, because multiple shrooms only refresh "
        "the poison duration and never stack.",
        "E (Toxic Shot) prices the on-hit PLUS the full 4-second poison: "
        "4 ticks of Magic Damage per Tick (== Total Poison Damage) at "
        "1-second intervals (this module's packet timing declaration); the "
        "poison refreshes rather than stacks (wiki note).",
        "The shroom slow (30/40/50% by R rank for 4 seconds) and reveal "
        "are crowd-control/vision utility the fight model does not price.",
        "Trap placement, arm time, trigger radius and the shroom's 6-HP "
        "trap health bar are state outside the damage model.",
    ]
)
OPTIONS.append(
    {
        "key": "r_shrooms",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 5,
        "label": "Shroom detonations (Noxious Trap)",
    }
)
ASSUMPTIONS.extend(
    [
        "W (Move Quick) deals no damage; its ACTIVE grant "
        "(24/32/40/48/56% for 3s) is published as a move_speed_percent "
        "stat buff, time-weighted by buff_window_share over that 3-second "
        "window: a stat_buff is one scalar for the whole fight, so an "
        "unweighted term would read the same in a 5s fight and a 30s one. "
        "The window is cached PROSE, not an atom (the slot's one "
        "timing.active_duration atom reads 5.0 and is the PASSIVE's "
        "idle condition, not the cast's window), so it is a HARDCODED "
        "module constant — the Udyr-E / Singed-R precedent. "
        "The passive branch is withheld: its 5s-undamaged condition is a "
        "state a fight never enters. Move-speed-reading item passives "
        "(Swiftmarch's adaptive force) are resolved from the build's "
        "stats before any cast, so they do not grow with the buff — the "
        "same fight-start boundary every stat_buff has.",
        "P (Guerrilla Warfare) stays out_of_scope, NOT no_damage (the "
        "Olaf-R rule): Element of Surprise grants 20/40/60/80% (based on "
        "level) bonus attack speed for 5s on breaking stealth, a real "
        "sourced steroid that would change damage. It is withheld because "
        "the stealth's 1.5s-idle entry condition is a state the fight "
        "model never enters, and because the cache carries no leveling "
        "row for the magnitude (wiki prose and the game binary only).",
    ]
)
MODULE_COVERAGE = coverage(no_damage="W", out_of_scope="P")

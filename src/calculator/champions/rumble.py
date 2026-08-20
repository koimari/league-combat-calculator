"""Rumble — CP10.6 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (The Equalizer) priced ONE tick
of the Burning DoT.  The wiki cache carries "Magic Damage per Tick"
(30/50/70 + 8.75% AP) and "Maximum Magic Damage" (600/1000/1400 +
175% AP): 20 ticks at 0.25 seconds over up to 5 seconds of Burning
("Enemies may be Burning for up to 5 seconds, for a total of 20
instances of its effect"). This module's packet timing declaration
prices all 20 ticks.

Row-selection fix (Q): the generated packet read Flamespitter's "Bonus
Damage" row, which is neither a Flamespitter damage row nor rank-indexed
— it is the per-LEVEL monster cap the Danger Zone effect states
("Flamespitter's total damage based on the target's health is capped at
65 : 336.84 (based on level) against monsters"), and the packet indexed
its 20 level values by rank, so rank 5 priced the level-5 cap (107.71).
Flamespitter's own rows are Minimum / per-Second / per-Tick / Maximum
Magic Damage; this module prices the "Maximum Magic Damage" row
(62.5/93.75/125/156.25/187.5 + 131.25% AP + 7.5/8.13/8.75/9.38/10% of
the target's maximum health), which is the whole 3-second flamethrower
— 15 ticks of "Magic Damage per Tick" at every rank.

The Danger Zone half of the heat system stays unpriced: rotation
numbers assume no heat state (the CP-era review boundary), so Q/E/R
price their base rows and the Enhanced rows go unread.

Overheated, the other half, is now priced.  At 150 Heat Rumble's mech
"empowers his basic attacks to deal 5 : 44.12 (based on level) (+ 25%
AP) (+ 4% of the target's maximum health) bonus magic damage on-hit" —
a complete sourced on-hit row, gated by the explicit ``p_overheated``
option (default off, so a default request is unchanged).  What the
option does NOT price is the rest of the state: the 50% : 142.54%
bonus attack speed and the ability lockout arrive together, and the
engine can express the first but not the second, so pricing the attack
speed alone would make Overheating a free upgrade.  W (Scrap Shield) is
``no_damage`` — a shield and a movement-speed burst.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import extract_named, simple_damage

PACKET_SHA256 = "c18c1e6e7005c17066acf180ec68a2013bb656c20a88655a536f0a2bc9a078f5"

# Flamespitter's cadence is the cache's own, and it is stated twice.  The
# entry reads "Rumble generates 20 Heat to activate his flamethrower for 3
# seconds, spewing forth flames in a frontal cone every 0.25 seconds.
# Enemies hit by the flame are scorched for 0.6 seconds, taking magic
# damage every 0.25 seconds as well as upon being hit if not currently
# scorched" — flames at 0.00 through 3.00 are thirteen instances on the
# beat, and the last flame's 0.6-second scorch tails two more at 3.25 and
# 3.50.  Fifteen, which is exactly the ratio the rank rows already carry
# (Maximum Magic Damage == 15 x Magic Damage per Tick at every rank), the
# equality ``_flamespitter_full_channel`` re-checks against the cache.
_Q_TICKS = 15
_Q_TICK_INTERVAL = 0.25

_flamespitter = simple_damage(attr="Maximum Magic Damage", dmg_type="magic")


def _flamespitter_full_channel(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the full 3-second flamethrower on its sourced 0.25-second beat."""
    entry = _flamespitter(ctx)
    if entry is None:
        return None
    entry["target_max_health_sensitive"] = True
    ability = ctx.ability()
    rank = ctx.rank_for()
    per_tick = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    total = float(entry["total_raw"])
    # The cached rows are rounded to three decimals apiece, so they agree
    # to a tenth of a percent rather than exactly; a real change to the
    # tick count moves this ratio by 1/15th and trips the guard.
    if not math.isclose(per_tick * _Q_TICKS, total, rel_tol=1e-3):
        raise ValueError(
            "Rumble Q: the cached 'Magic Damage per Tick' x 15 no longer "
            "equals 'Maximum Magic Damage' - the 15-tick channel pinned "
            "here has changed upstream"
        )
    # One beat, authored as the cache states it: the first flame lands at
    # the cast (castTime is "none") and the fifteenth 3.5 seconds later.
    # The row's total stays the sourced Maximum row, split evenly, so the
    # rounding above never leaks into the number.
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _Q_TICKS,
            count=_Q_TICKS,
            time_offset=0.0,
            hit_interval=_Q_TICK_INTERVAL,
            cc_kind="none",
        ),
    )
    entry["detail"] = (
        f"{_Q_TICKS} ticks at {_Q_TICK_INTERVAL:g}-second intervals "
        "(3-second flamethrower plus the last flame's 0.6-second scorch)"
    )
    return entry


_flamespitter_full_channel.phase = "damage"


def _junkyard_titan(packet_passive):
    """P: the packet's Heat row, plus the Overheated on-hit rider.

    The compiled row is kept whole — with the option off this returns
    exactly what the packet compiled — and the rider is added on top, so
    the sourced "Bonus Magic Damage" leveling (flat by level + 25% AP +
    4% of the target's maximum health) reaches the fight through the same
    ability-on-hit channel Kog'Maw W uses.  The monster cap on the health
    share ("Bonus Damage", 65 : 163.32 by level) is not read: this
    calculator's target is a champion.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_passive(ctx)
        if entry is None or not ctx.options.get("p_overheated", False):
            return entry
        ability = ctx.ability()
        if ability is None:
            return entry
        per_hit = extract_named(
            ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
        )
        entry["on_hit"] = {
            "name": "Junkyard Titan (Overheated)",
            "damage_per_hit": per_hit,
            "damage_type": "magic",
        }
        entry["target_max_health_sensitive"] = True
        entry["detail"] = (
            f"Overheated: every basic attack deals {per_hit:.2f} bonus "
            "magic damage on-hit (5 : 44.12 by level + 25% AP + 4% of the "
            "target's maximum health).  Overheating's bonus attack speed "
            "and its ability lockout are both unmodeled."
        )
        return entry

    return parse


# Cached kit review.  E's harpoon deals magic damage while "inflicting them
# with magic resistance reduction ... and slowing them for 2 seconds" — the
# shred is a resistance effect, the slow is the control.  R's field marks
# enemies burning, "taking magic damage every 0.25 seconds and being slowed
# by 35%".  Q's flames only scorch: the entry's damage clauses carry no
# control word, so the answer is a reviewed "none", and the fifteen ticks
# authored above are what carries it to the event ledger.  W is a shield,
# and P authors no ability damage part either: the Overheated rider is an
# on-hit that rides the basic-attack stream, which carries no ability
# event for a kind to answer for.
MODULE_CC = {"E": "slow", "Q": "none", "R": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rumble",
    PACKET_SHA256,
    packet_tick_fixes={
        "The Equalizer": {
            "count": 20,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 5.0,
        }
    },
    # The harpoon "deals magic damage to the first enemy hit" once — the
    # boundary claim that carries MODULE_CC's reviewed answer for E into
    # the event ledger.  R already authors its own twenty-tick timing.
    single_hit_slots=frozenset({"E"}),
    slot_parsers={"Q": _flamespitter_full_channel},
    slot_wrappers={"P": _junkyard_titan},
    cc_kinds=MODULE_CC,
)
OPTIONS = list(OPTIONS) + [
    {
        "key": "p_overheated",
        "type": "bool",
        "default": False,
        "label": "Overheated (150 Heat): basic attacks deal bonus magic damage",
        "rotation": {"role": "self_state", "slot": "P"},
    },
]
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Flamespitter) prices the cached Maximum Magic Damage row "
    "(62.5/93.75/125/156.25/187.5 + 131.25% AP + 7.5% : 10% of the "
    "target's maximum health) — the whole 3-second flamethrower, equal "
    "to 15 x Magic Damage per Tick at every rank.  The generated packet "
    "read the Danger Zone effect's per-level Bonus Damage row, which is "
    "the monster damage cap and is indexed by level, not rank.  The row "
    "lands as 15 ticks at 0.25-second intervals from the cast, the "
    "cadence the cached entry states ('spewing forth flames ... every "
    "0.25 seconds', plus the last flame's 0.6-second scorch).  The "
    "Danger Zone (Enhanced) rows remain unpriced.",
    "R (The Equalizer) prices all 20 Burning ticks (Magic Damage per "
    "Tick x20 == Maximum Magic Damage 600/1000/1400 + 175% AP) at "
    "0.25-second intervals over up to 5 seconds (packet_module "
    "local packet timing declaration). The initial rocket impact has no separate "
    "damage row in the cache.",
    "The Danger Zone (50+ Heat) empower is state outside the damage "
    "model: Q/E/R rotation numbers assume no heat state (the CP-era "
    "review boundary).",
    "P (Junkyard Titan) prices the Overheated rider behind the explicit "
    "p_overheated option (default off): the sourced Bonus Magic Damage "
    "leveling (5 : 44.12 by level + 25% AP + 4% of the target's maximum "
    "health) on every basic attack of the fight.  Overheating's real 4s "
    "window, its Heat cost, its 50% : 142.54% bonus attack speed and its "
    "ability lockout are not modeled — the attack speed is left out "
    "deliberately, because granting it without the lockout would price "
    "Overheating as a pure gain.",
]
MODULE_COVERAGE = {
    slot: ("no_damage" if slot == "W" else "modeled") for slot in "PQWER"
}

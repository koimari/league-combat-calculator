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

The heat/Danger Zone system remains documented out_of_scope (P/W
no_damage rows); rotation numbers assume no heat state (the CP-era
review boundary).  E's damage packet is correct.
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

# Cached kit review.  E's harpoon deals magic damage while "inflicting them
# with magic resistance reduction ... and slowing them for 2 seconds" — the
# shred is a resistance effect, the slow is the control.  R's field marks
# enemies burning, "taking magic damage every 0.25 seconds and being slowed
# by 35%".  Q's flames only scorch: the entry's damage clauses carry no
# control word, so the answer is a reviewed "none", and the fifteen ticks
# authored above are what carries it to the event ledger.  W (a shield) and
# P (the heat system) carry no damage row at all.
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
    cc_kinds=MODULE_CC,
)
PACKET_SPEC = SLOTS.packet_spec
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
    "The heat/Danger Zone system is state outside the damage model: "
    "Q/E/R rotation numbers assume no heat state (the CP-era review "
    "boundary).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}

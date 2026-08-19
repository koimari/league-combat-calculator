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

from typing import Any

from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import simple_damage

PACKET_SHA256 = "c18c1e6e7005c17066acf180ec68a2013bb656c20a88655a536f0a2bc9a078f5"

_flamespitter = simple_damage(attr="Maximum Magic Damage", dmg_type="magic")


def _flamespitter_full_channel(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the full 3-second flamethrower, not the monster cap."""
    entry = _flamespitter(ctx)
    if entry is not None:
        entry["target_max_health_sensitive"] = True
    return entry


_flamespitter_full_channel.phase = "damage"

# Cached kit review.  E's harpoon deals magic damage while "inflicting them
# with magic resistance reduction ... and slowing them for 2 seconds" — the
# shred is a resistance effect, the slow is the control.  R's field marks
# enemies burning, "taking magic damage every 0.25 seconds and being slowed
# by 35%".  Q is deliberately absent rather than "none", and it is why a
# Rumble fight still reads coarse for control-armed items: Flamespitter is
# a 3-second flamethrower ticking "every 0.25 seconds" that this module
# prices as one aggregate row with no per-tick timing, so no event of its
# own could carry an answer.  Its flames apply no control either way; the
# missing piece is the ledger boundary, not the reading.  W (a shield) and
# P (the heat system) carry no damage row at all.
MODULE_CC = {"E": "slow", "R": "slow"}

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
    "the monster damage cap and is indexed by level, not rank.  Per-tick "
    "timing and the Danger Zone (Enhanced) rows remain unpriced.",
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
REVIEW_STATUS = "reviewed_module"

"""Poppy — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Iron Ambassador (P): the reviewed packet priced only the
%max-HP "Max Health Damage" row (0.11-0.2106, which is actually the
SHIELD the buckler grants when Poppy retrieves it, not damage) with a
zero base and dropped the flat damage term.  The wiki text is:
"Poppy's next basic attack ... deal[ing] 20 : 198.82 (based on level)
bonus magic damage" (data/champions.json P "Bonus Magic Damage" row),
so the passive is an on-hit entry priced at the per-level flat value.

2026-08-20 packet refresh (16.16.1 re-pull) — Q (Hammer Shock): the
reviewed packet was pinned to a pre-16.16.1 champions.json snapshot and
had drifted from the current data/champions.json "Physical Damage" row
in two fields: the bonus-AD ratio (100% flat -> 75% flat at every rank)
and the target-max-HP ratio (9% flat at every rank -> 7/7.5/8/8.5/9%,
now rank-scaling). Regenerated via
``LCC_WIKI_DB=<real wiki revision index> scripts/build_reviewed_modules.py``
against the current data/champions.json and spliced into
static/reviewed-packets.json (only the Poppy entry changed; the other
172 champion entries and their PACKET_SHA256 pins are untouched).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx
from .inputs import bool_option
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    with_control,
)

PACKET_SHA256 = "b6f179d37816f86a3c589048738bf588034d2340535ad6dde533391daf113d90"


def _iron_ambassador(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the empowered buckler toss deals 20 : 198.82 (based on level)
    bonus magic damage on-hit — the "Bonus Magic Damage" leveling row."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    return on_hit_entry(ability_name(ability), per_hit, "magic")


_iron_ambassador.phase = ONHIT


def _keepers_verdict(packet_r):
    """R: Keeper's Verdict, priced at the charged or uncharged branch.

    The reviewed packet prices the UNCHARGED row ("Physical Damage"
    100-200 + 45% bonus AD).  Keeper's Verdict can be charged for up to
    1 second to deal double damage (the E3 worklist charge-state
    variant); the cached "Increased Damage" row (200-400 + 90% bonus AD)
    is that fully-charged branch, selected by the ``r_charged`` option.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        if not bool(ctx.option("r_charged")):
            return packet_r(ctx)
        ranked = ctx.ranked("R")
        if ranked is None:
            return None
        ability, rank = ranked
        total = extract_named(ability, "Increased Damage", rank, ctx.stats, ctx.target)
        entry = damage_entry(
            ability_name(ability),
            rank,
            extract_cooldown(ability, rank),
            total,
            "physical",
            # One hammer blow, like the uncharged packet branch beside it.
            event_order_certified="single_hit",
        )
        entry["parts"] = (DamagePart("physical", total),)
        entry["detail"] = (
            "fully-charged Keeper's Verdict ('Increased Damage' row 200-400 "
            "+ 90% bonus AD == 2x the uncharged row)"
        )
        return entry

    return parse


# Cached kit review.  Q's impact "creates a field for 1 second that slows
# enemies within, which then ruptures to deal the same physical damage".  W
# damages a dashing enemy and "knocked up for 0.5 seconds" (its grounding
# and 25% slow follow only a successful interrupt, and neither is what the
# damaging hit applies first).  E is the kit's un-narrowed cast: it "deals
# physical damage and carries them along with her" — a forced displacement
# — and on terrain "deal[s] the same physical damage again and stuns
# them", two immobilize kinds from one cast.  R "knock[s] them up for 1
# second" in both priced branches; the fully-charged branch adds a knock
# back on top, which is a second immobilize and not a different answer.
# P is absent — Iron Ambassador is an on-hit rider on the auto stream.
MODULE_CC = {"Q": "slow", "W": "knockup", "E": "immobilize", "R": "knockup"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Poppy",
    PACKET_SHA256,
    assumption_overrides=(
        "Poppy Q's sourced Hammer Shock field ruptures 1 second after impact; "
        "the packet emits both physical hits.",
    ),
    packet_part_timings={
        "Q": {
            "count": 2,
            "time_offset": 0.0,
            "hit_interval": 1.0,
            "total_multiplier": 2.0,
        }
    },
    # Steadfast Presence damages a dashing enemy once, Heroic Charge lands
    # its hit on arrival and the uncharged Keeper's Verdict is one hammer
    # blow — the boundary claim that carries MODULE_CC's reviewed answers
    # into the event ledger.  Q already authors its impact/rupture timing.
    single_hit_slots=frozenset({"W", "E", "R"}),
    slot_parsers={
        "P": _iron_ambassador,
    },
    slot_wrappers={
        "R": _keepers_verdict,
        # "Stun Duration" is the only interval the cache prices for the
        # cast, so the reviewed immobilize reads its length from there
        # rather than carrying an unsourced one.
        "E": lambda compiled: with_control(compiled, duration_attr="Stun Duration"),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    bool_option("r_charged", False, label="Fully-charged Keeper's Verdict (R)"),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Iron Ambassador) deals 20 : 198.82 (based on level) bonus magic "
    "damage on the empowered buckler attack — the wiki's 'Bonus Magic "
    "Damage' row (data/champions.json). The old packet's %max-HP "
    "0.11-0.2106 'Max Health Damage' row is the shield Poppy gains when "
    "she retrieves the buckler, not damage, and is not priced.",
    "R (Keeper's Verdict) defaults to the reviewed packet's uncharged "
    "row ('Physical Damage' 100-200 + 45% bonus AD); the fully-charged "
    "branch (the E3 worklist charge-state variant, 'Increased Damage' "
    "200-400 + 90% bonus AD == 2x) is option-gated via r_charged — the "
    "1-second charge time is state.",
]

"""Yone — Gathering Storm (Q3) stack system.

Stack mechanics modeled (E3):
- Q (Mortal Steel): Gathering Storm stacks up to 2 (6-second window).
  At 2 stacks the next Q cast consumes them to become the Q3 whirlwind.
  The whirlwind deals the SAME sourced damage as a normal Q — the
  empower is a 0.75-second knock-up (CC state, not damage).
  ``q_gathering_storm`` is the explicit pre-stack state.
- P (Way of the Hunter): the soul-mark / spirit-form store is a state
  row.
- E (Soul Unbound) (E9-3): Spirit Form stores a portion of the
  post-mitigation physical and magic damage dealt to champions, then the
  recast deals that stored amount as true damage. The fight engine applies
  this from the authored ability and auto-attack event ledger.

W (Spirit Cleave) and R (Fate Sealed) read the sourced physical and magic
rows. All numeric values are read from the champion JSON data.
"""

from __future__ import annotations

# pylint: disable=duplicate-code  # Yone deliberately mirrors Yasuo's Q/P
# crit-conversion shape (the shared module_helpers rule); the parallel
# blocks are the documented contract, not accidental duplication.
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import (
    CRIT_CHANCE_MULTIPLIER,
    CRIT_DAMAGE_MULTIPLIER_FACTOR,
    EXCESS_CRIT_BONUS_AD_PER_PERCENT,
    crit_conversion_certification,
    crit_conversion_payload,
    no_damage,
)
from .packet_module import build_packet_module
from .source_receipts import load_champion_sources
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value

# P4: the crit-conversion rule is the shared module_helpers rule (the
# 0.9 factor's atom hash is 1142fbe0a600fcc8 for Yone).
(
    _CRIT_CHANCE_MULTIPLIER,
    _CRIT_DAMAGE_MULTIPLIER_FACTOR,
    _EXCESS_CRIT_BONUS_AD_PER_PERCENT,
) = (
    CRIT_CHANCE_MULTIPLIER,
    CRIT_DAMAGE_MULTIPLIER_FACTOR,
    EXCESS_CRIT_BONUS_AD_PER_PERCENT,
)
CERTIFIED_CONSTANTS, ATOM_IDS = crit_conversion_certification("1142fbe0a600fcc8")
certified_constants, atom_ids = CERTIFIED_CONSTANTS, ATOM_IDS

# HARDCODED: verify on patch updates — the 5-second Spirit Form window
# and the +0.5s earliest recast are prose in the cached E description
# ("entering Spirit Form for 5 seconds" / "can be recast after 0.5
# seconds, and automatically does so after the duration"); the stored
# percentage is the cached "Damage Stored" row read live.
_E_SPIRIT_FORM_SECONDS = 5.0

PACKET_SHA256 = "806d48d7af49a8e38076a40e8ab180ee25751185eb1c7a31caf2b97e338aaaf1"


def _way_of_the_hunter(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: soul-mark state row (no enemy damage) + the crit conversion.

    The P4 fix: Yone's P carries the SAME crit_modifier payload as
    Yasuo's (the cached P prose is verbatim Yasuo's; the 0.9
    criticalStrikeDamageModifier stat is in the cache for both) so the
    engine converts Yone's crit chance (x2), reduces the crit damage
    (x0.9), and grants 0.5 AD per excess % — for autos AND the Q's
    AD-ratio part.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    entry = no_damage(
        ctx,
        name=ability.get("name", "Way of the Hunter"),
        reason=(
            "Soul Unbound's mark stores 25/27.5/30/32.5/35% of post-"
            "mitigation damage dealt during Spirit Form (E row); the "
            "mark itself deals no direct damage."
        ),
    )
    if entry is not None:
        entry["crit_modifier"] = crit_conversion_payload()
        entry["certified_constants"] = dict(CERTIFIED_CONSTANTS)
        entry["atom_ids"] = dict(ATOM_IDS)
    return entry


def _mortal_steel(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Mortal Steel, empowered into the Q3 whirlwind at 2 Gathering Storm stacks."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.options.get("q_gathering_storm", 0)), 0), 2)
    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Mortal Steel"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    # P4: the flat/AD-ratio split (Yasuo's shape) — only the AD-ratio
    # portion crits ("Steel Tempest's damage based on its AD ratio can
    # critically strike"; the binary TotalDamageCrit = base + AD x
    # (crit stat x ratio)).
    flat = extract_value(ability, "Physical Damage", rank, 0)
    ad_ratio = extract_value(ability, "Physical Damage", rank, 1) / 100.0
    ad_part = ctx.stats.get("attack_damage", 0.0) * ad_ratio
    if stacks >= 2:
        # The Q3 whirlwind: same sourced damage + the 0.75s knock-up
        # (the binary Q3KnockupDuration 0.75) — CC state on the flat
        # part, mirroring Yasuo's Q3.
        entry["parts"] = (
            DamagePart(
                "physical",
                flat,
                cc_kind="knockup",
                cc_duration=0.75,
                time_offset=0.0,
            ),
            DamagePart("physical", ad_part, crit_effectiveness=1.0),
        )
        entry["detail"] = (
            "Gathering Storm at 2 stacks: this cast is the Q3 whirlwind — "
            "same sourced damage as a normal thrust, adding a 0.75s "
            "knock-up (crowd-control state, not damage)."
        )
    else:
        entry["parts"] = (
            DamagePart("physical", flat),
            DamagePart("physical", ad_part, crit_effectiveness=1.0),
        )
        entry["detail"] = (
            f"Gathering Storm {stacks}/2 stacks; the Q3 whirlwind at 2 "
            "stacks deals the same sourced damage (the empower is the "
            "knock-up, a crowd-control state)."
        )
    return entry


def _mixed_damage_entry(
    ctx: SlotCtx,
    *,
    attributes: tuple[tuple[str, str], ...],
) -> dict[str, Any] | None:
    """Build one mixed packet from its sourced physical and magic rows."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    parts = tuple(
        DamagePart(
            damage_type,
            extract_named(ability, attribute, rank, ctx.stats, ctx.target),
        )
        for damage_type, attribute in attributes
    )
    total = sum(part.amount for part in parts)
    entry = damage_entry(
        ability.get("name", f"Ability {ctx.slot}"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "mixed",
    )
    entry["parts"] = parts
    entry["total_raw"] = total
    entry["detail"] = "Sourced physical and magic damage instances"
    return entry


def _spirit_cleave(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: physical damage lands before the equal magic damage instance."""
    return _mixed_damage_entry(
        ctx,
        attributes=(
            ("physical", "Physical Damage"),
            ("magic", "Magic Damage"),
        ),
    )


def _fate_sealed(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: magic damage lands before the equal physical damage instance."""
    return _mixed_damage_entry(
        ctx,
        attributes=(
            ("magic", "Magic Damage"),
            ("physical", "Physical Damage"),
        ),
    )


_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module(
        "Yone",
        PACKET_SHA256,
        single_hit_slots=frozenset({"W"}),
        slot_parsers={"W": _spirit_cleave, "R": _fate_sealed},
    )
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec


def _soul_unbound(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: declare a post-mitigation damage store for the fight engine."""
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    ratio = extract_value(ability, "Damage Stored", rank, 0) / 100.0
    entry = damage_entry(
        ability.get("name", "Soul Unbound"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "true",
    )
    entry["parts"] = ()
    entry["stored_damage"] = {
        "ratio": ratio,
        "duration": _E_SPIRIT_FORM_SECONDS,
        "source_slots": ("Q", "W", "R"),
        "include_auto_attacks": True,
    }
    entry["detail"] = (
        f"{ratio * 100:g}% of post-mitigation physical and magic champion "
        "damage during Spirit Form, re-dealt as true damage at the "
        "five-second auto-recast"
    )
    return entry


SLOTS = {
    "P": _way_of_the_hunter,
    "Q": _mortal_steel,
    "W": _spirit_cleave,
    "R": _fate_sealed,
    # E declares metadata consumed after the fight event ledger is authored.
    "E": _soul_unbound,
}
parse_abilities = build_parser(SLOTS, "Yone")

OPTIONS = [
    {
        "key": "q_gathering_storm",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "Gathering Storm stacks (2 = Q3 ready)",
    },
]

ASSUMPTIONS = [
    "Q3 (Gathering Storm at 2 stacks) deals the same sourced damage as a "
    "normal Q; its empower is the 0.75s knock-up, modeled as crowd-"
    "control state, so q_gathering_storm only changes the Q row's detail",
    "P (Way of the Hunter) soul mark is state",
    "E (Soul Unbound) stores the sourced percentage of post-mitigation "
    "physical and magic champion damage from Q/W/R and basic attacks "
    "inside each five-second Spirit Form window. The fight engine emits "
    "the stored amount as a true-damage recast event.",
    "W (Spirit Cleave) uses the sourced physical row followed by the "
    "sourced magic row.",
    "R (Fate Sealed) uses the sourced magic row followed by the sourced "
    "physical row.",
]

SOURCES = load_champion_sources("Yone")
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"

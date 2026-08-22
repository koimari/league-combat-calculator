"""Rengar — Ferocity (4-stack) empowered-ability system.

Stack mechanics modeled (E3):
- P (Unseen Predator): casting a basic ability generates a Ferocity
  stack (cap 4). At maximum stacks the next basic ability consumes them
  to become EMPOWERED: the empowered Q/W/E replaces the base ability's
  damage with the wiki "Ferocity Bonus" sourced values (per-level
  arrays). ``p_ferocity`` is the explicit pre-stack state; at 4 the
  Q/W/E rows price the empowered values.
- Q (Savagery) base: "Additional Physical Damage" (20 : 160 by rank
  + 5% AD); empowered: "Bonus Physical Damage" (35 : 260 by level
  + 20% AD).  The reviewed CP10.6 packet misread the per-level
  Ferocity-Bonus array as per-rank base damage; this module prices the
  rank array for base and the level array for the empower.
- W (Battle Roar) base: "Magic Damage" (50 : 170 + 80% AP); empowered:
  "Bonus Magic Damage" (50 : 240 by level + 80% AP).
- E (Bola Strike) base: "Physical Damage" (55 : 235 + 80% bonus AD);
  empowered: "Bonus Physical Damage" (50 : 335 by level + 80% bonus AD).

R (Thrill of the Hunt) is not a self buff.  Its priced effect is the
armour reduction the empowered attack leaves on the target — "then
inflicts armor reduction for 4 seconds", the cached "Armor Reduction"
row (15/20/25) — emitted as a ``target_debuff`` the fight engine shreds
with (``engine.py`` ``_ALLOWED_DEBUFF_KEYS``).  All numeric values are
read from the champion JSON data.

What R still does NOT price is the ambush attack's damage rider —
"deals 100% AD additional physical damage" — and that stays open on
sourced grounds: rengar.bin.json
RengarRAbility/RengarR carries mSpellCalculations.BonusDamage
(StatByCoefficientCalculationPart, mStat=2 = bonus AD, coefficient 1.0)
against wiki prose reading an ambiguous "100% AD", and an ArmorShred
DataValues array of 7 values ([10,15,20,25,30,35,40]) against the
wiki's 3-value leveling row — two authority conflicts — while no
marked-target / Unseen-Predator proc-condition kernel exists to gate a
"next basic attack against the marked enemy" trigger.  A
discovered-but-unresolved formula stays named and unpriced rather than
being mislabelled in either direction (the Dr. Mundo P precedent).
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from ..state_lifecycle import SourceReceipt, StackRule, TimedStackState
from .engine import CC_PER_PART, DEBUFF, SlotCtx
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .inputs import bool_option, int_option

PACKET_SHA256 = "bc9f962c63c4eaabd3333b892d9f7d876578e1d3ae0f9fe1fb0256afb3232d50"

_FEROCITY_MAX = 4

# HARDCODED: verify on patch updates — the shred's window is cached R
# prose ("then inflicts armor reduction for 4 seconds"); the magnitude
# is the JSON's "Armor Reduction" row.
_R_SHRED_SECONDS = 4.0


def _thrill_of_the_hunt(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the empowered attack's flat armour shred on the marked target."""
    ranked = ctx.ranked("R")
    if ranked is None:
        return None
    ability, rank = ranked

    landed = bool(ctx.option("r_thrill_attack"))
    shred = extract_value(ability, "Armor Reduction", rank)
    movement = extract_value(ability, "Bonus Movement Speed", rank)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    if landed and shred > 0.0:
        entry["target_debuff"] = {
            "armor_reduction_flat": shred,
            "duration": _R_SHRED_SECONDS,
        }
    entry["detail"] = (
        f"the empowered attack shreds {shred:g} armour for "
        f"{_R_SHRED_SECONDS:g}s (the engine weights it by the share of "
        "the fight the window covers, timed from the cast rather than "
        "from the attack that lands it 2s later); the row's "
        f"+{movement:g}% movement speed, the camouflage and the 100% AD "
        "rider on that attack have no channel here"
        if landed
        else (
            "not armed: r_thrill_attack is off, so no empowered attack "
            f"lands and the {shred:g} armour shred is not applied"
        )
    )
    return entry


_thrill_of_the_hunt.phase = DEBUFF


# Ferocity is a typed kernel state (state_lifecycle.StackRule).  The
# numbers are prose in the reviewed cache entry (Rengar P effect 0:
# "Rengar generates a stack of Ferocity for 1 second, stacking up 4 times
# but not refreshing on subsequent triggers (unexpected) ... Generated
# Ferocity is prevented from expiring for 10 seconds after dealing or
# taking damage, excluding damage dealt by damage over time or proc
# effects."), so the module pins them beside the P template source
# receipt.  The 1-second value comes from the 2019 P template revision
# (Data_Rengar/I rev 2864152) — the same revision the module's SOURCES
# publishes; verify against current game files on patch updates.
RENGAR_FEROCITY_STACK_RULE = StackRule(
    name="Rengar — Unseen Predator (Ferocity stacks)",
    max_stacks=4,
    gain_per_application=1,
    duration_seconds=1.0,
    refresh="none",
    expiry="all_at_once",
    cap_behavior="noop",
    combat_extension_seconds=10.0,
    source=SourceReceipt(
        label="Local League Wiki cache — Rengar P effect prose",
        url="https://wiki.leagueoflegends.com/en-us/Template:Data_Rengar/I",
        revision_id=2864152,
        revision_timestamp="2019-11-03T20:06:28Z",
    ),
)


def _ferocity_bonus(
    ctx: SlotCtx, ability: dict[str, Any], attribute: str
) -> float | None:
    """Extract the Ferocity-Bonus leveling value for one ability.

    The W ability stores two "Bonus Magic Damage" arrays (the monster
    bonus and the Ferocity bonus); the Ferocity one is the effect whose
    description carries "Ferocity Bonus".  Returns None when absent.
    """
    for effect in ability.get("effects", []):
        if "Ferocity Bonus" not in effect.get("description", ""):
            continue
        leveling = find_named_leveling({"effects": [effect]}, attribute)
        if leveling is None:
            return None
        return sum_modifiers(leveling, ctx.level, ctx.stats, ctx.target)
    return None


def _ferocity_state(ctx: SlotCtx) -> TimedStackState:
    """The kernel-owned Ferocity stack state seeded from the option.

    ``p_ferocity`` is the pre-stack state; in-fight gains are not wired.
    """
    return TimedStackState(
        RENGAR_FEROCITY_STACK_RULE,
        starting_stacks=max(0, min(int(ctx.option("p_ferocity")), _FEROCITY_MAX)),
    )


def _ferocity(ctx: SlotCtx) -> int:
    return _ferocity_state(ctx).stacks


def _unseen_predator(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Ferocity stack state row (no enemy damage)."""
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = _ferocity(ctx)
    state = (
        "next basic ability is EMPOWERED (consumes all 4 stacks)"
        if stacks >= _FEROCITY_MAX
        else f"{stacks}/4 Ferocity stacks; at 4 the next basic ability is empowered"
    )
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"Ferocity: {state}.  Bonetooth Necklace trophies (up to 5, "
            "1-36% bonus AD) are state; brush leap is mobility state."
        ),
    )


def _savagery(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Savagery — base or Ferocity-empowered (level array) bonus damage."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    # Both part sets are emitted unconditionally (P3 package 3V): the
    # engine prices the FEROCITY parts for a live empowered cast (the
    # post-rotation stack walk's consume) and the base parts otherwise,
    # so the seeded static read below only drives the parse detail text.
    base_bonus = extract_named(
        ability, "Additional Physical Damage", rank, ctx.stats, ctx.target
    )
    ferocity_bonus = _ferocity_bonus(ctx, ability, "Bonus Physical Damage") or 0.0
    empowered = _ferocity(ctx) >= _FEROCITY_MAX
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        ferocity_bonus if empowered else base_bonus,
        "physical",
        event_order_certified="single_hit",
    )
    # The engine prices the BASE parts by default and the FEROCITY parts
    # only for a live empowered cast (the post-rotation consume); the
    # seeded total_raw remains the headline the parse panel shows.
    entry["parts"] = (DamagePart("physical", base_bonus),)
    entry["ferocity_parts"] = (DamagePart("physical", ferocity_bonus),)
    if empowered:
        entry["detail"] = (
            "Ferocity-empowered: 35 : 260 by level + 20% AD (the wiki "
            "Ferocity Bonus), consuming all 4 stacks."
        )
    else:
        entry["detail"] = (
            "Base Savagery: 20 : 160 by rank + 5% AD on the first "
            "empowered basic attack; the attack can crit at "
            "(100% + 30%) AD effectiveness."
        )
    return entry


def _battle_roar(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Battle Roar — base or Ferocity-empowered (level array) magic damage."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    base_damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    ferocity_damage = _ferocity_bonus(ctx, ability, "Bonus Magic Damage") or 0.0
    empowered = _ferocity(ctx) >= _FEROCITY_MAX
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        ferocity_damage if empowered else base_damage,
        "magic",
        event_order_certified="single_hit",
    )
    entry["parts"] = (DamagePart("magic", base_damage),)
    entry["ferocity_parts"] = (DamagePart("magic", ferocity_damage),)
    if empowered:
        entry["detail"] = (
            "Ferocity-empowered: 50 : 240 by level + 80% AP (the wiki "
            "Ferocity Bonus), consuming all 4 stacks."
        )
    else:
        entry["detail"] = (
            "Base Battle Roar: 50 : 170 by rank + 80% AP; the grey-health "
            "heal is state."
        )
    return entry


def _bola_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Bola Strike — base or Ferocity-empowered (level array) physical damage.

    E is declared ``CC_PER_PART`` because the Ferocity bonus changes the
    kind: the base bola "slows them for 1.75 seconds",
    and the empowered one roots "instead of slowed".
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    base_damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    ferocity_damage = _ferocity_bonus(ctx, ability, "Bonus Physical Damage") or 0.0
    empowered = _ferocity(ctx) >= _FEROCITY_MAX
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        ferocity_damage if empowered else base_damage,
        "physical",
        event_order_certified="single_hit",
    )
    # The two part sets carry the two crowd-control answers with them, so
    # whichever set the engine prices states the control that cast applied.
    entry["parts"] = (DamagePart("physical", base_damage, cc_kind="slow"),)
    entry["ferocity_parts"] = (DamagePart("physical", ferocity_damage, cc_kind="root"),)
    if empowered:
        entry["detail"] = (
            "Ferocity-empowered: 50 : 335 by level + 80% bonus AD (the "
            "wiki Ferocity Bonus), consuming all 4 stacks; the target "
            "is rooted instead of slowed."
        )
    else:
        entry["detail"] = (
            "Base Bola Strike: 55 : 235 by rank + 80% bonus AD; the bola "
            "slows the first enemy hit for 1.75 seconds."
        )
    return entry


# Cached kit review.  Q's empowered stab only "deal[s] additional physical
# damage" and W's roar "deal[s] magic damage to nearby enemies" while
# healing Rengar — neither applies control in either Ferocity branch.  E
# answers per cast because its Ferocity bonus changes the kind
# (``_bola_strike``).  R is absent: Thrill of the Hunt's damage row is the
# empowered basic attack's armour reduction rider, which the reviewed
# packet prices as no enemy-damage of its own, and P is the Ferocity state
# row.
MODULE_CC = {"Q": "none", "W": "none", "E": CC_PER_PART}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rengar",
    PACKET_SHA256,
    assumption_overrides=(
        "W (Battle Roar) stores 50% of post-mitigation damage taken in the last 1.5 seconds as "
        "grey health and the active heals the stored pool (the E8a grey-health primitive authors "
        "the heal from the incoming ledger at each W cast)",
        "Ferocity is a typed kernel stack state: cap 4, each stack lasts 1 second, subsequent "
        "triggers do not refresh the timer, and expiry is prevented for 10 seconds after dealing "
        "or taking damage (excluding DoT/proc damage); at 4 stacks the next Q/W/E cast is "
        "empowered and prices the wiki Ferocity Bonus values, consuming all stacks.  The 1-second "
        "value is prose in the reviewed P template (rev 2864152); live in-fight gains are not "
        "wired: the rotation resolver does not feed per-cast stack events into champion-module "
        "parses (named reason), so the fight starts from the seeded state and the kernel receipt "
        "documents the rule",
        "p_ferocity is the explicit pre-stack state; 0 prices base Q/W/E",
        "The reviewed CP10.6 packet misread Q's per-level Ferocity Bonus array as per-rank base "
        "damage; this module prices base Q from the rank array (20 : 160 + 5% AD) and the empower "
        "from the level array (35 : 260 + 20% AD)",
        "R (Thrill of the Hunt) prices its armour reduction as a target_debuff: the cached Armor "
        "Reduction row (15/20/25) for the sourced 4 seconds, applied when r_thrill_attack is on "
        "(default).  The engine weights the shred by the share of the fight its window covers, "
        "timed from the cast rather than from the empowered attack that lands 2 seconds later, "
        "and the 100% AD rider on that attack, the camouflage and the movement speed are not "
        "priced.  That rider stays unpriced on sourced grounds: rengar.bin.json RengarR carries "
        "mSpellCalculations.BonusDamage (mStat=2 bonus AD, coefficient 1.0) against the wiki's "
        "ambiguous '100% AD' prose, and a 7-value ArmorShred DataValues array against the wiki's "
        "3-value leveling row, and no marked-target / Unseen-Predator proc-condition kernel "
        "exists to gate the ambush attack",
    ),
    slot_parsers={
        "P": _unseen_predator,
        "Q": _savagery,
        "W": _battle_roar,
        "E": _bola_strike,
        "R": _thrill_of_the_hunt,
    },
    slot_order=("P", "Q", "W", "E", "R"),
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    int_option(
        "p_ferocity",
        0,
        minimum=0,
        maximum=4,
        label="Ferocity stacks (4 = empowered next)",
        state=RENGAR_FEROCITY_STACK_RULE.public_receipt(),
    ),
    bool_option(
        "r_thrill_attack",
        True,
        label="Thrill of the Hunt's empowered attack lands (armour shred)",
        rotation={
            "role": "self_state",
            "slot": "R",
            "note": (
                "Arms R's own armour shred, which is already a parsed "
                "target_debuff atom."
            ),
        },
    ),
]


# No MODULE_COVERAGE: every one of the five slots emits a priced row now
# (R's is the target_debuff armour shred).

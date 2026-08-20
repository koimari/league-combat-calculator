"""Rek'Sai — CP10.6 full-entry-reviewed packet module, plus the P1 max-Fury E.

P1 addition over the reviewed packet:
- E (Furious Bite) prices the max-Fury branch: "At maximum Fury, Furious
  Bite deals 120% damage and is converted to true damage" (cached E
  second effect; the leveling row "True Damage" 84-204 + 72% bonus AD ==
  120% of the "Physical Damage" row at every rank).  Fury is player
  state, so the fight is deterministic through the ``e_fury`` option
  (0-100, default 0 = no Fury): at 100 Fury the E packet prices the
  sourced true-damage row, otherwise the reviewed physical row.

P (Fury of the Xer'Sai): "When Rek'Sai becomes Burrowed, she consumes her
current Fury over 3 seconds to heal for 0% : 100% (based on Fury) of
9% : 21.29% (based on level) maximum health" (cached P prose; the level
row is mislabelled ``Max Health Damage``).  Fury generation is player
state the duel does not simulate, so ``p_burrow_fury`` (0-100, default 0)
is the Fury the burrow that opens the fight consumes; the P row carries
the resulting amount and the self-heal rule places it at the first W.

Row-selection fix (Q variant 0): Queen's Wrath empowers Rek'Sai's next
basic attack, and "if Rek'Sai completes an attack, the duration is
refreshed, for up to 3 total empowered attacks".  The generated packet
priced "Bonus Physical Damage" (30/35/40/45/50% AD), one of the three;
the cache's "Total Bonus Physical Damage" row (90/105/120/135/150% AD)
is all three.  Three attacks is not one hit, so the variant declares its
aggregate at the cast boundary instead of certifying a single hit —
Prey Seeker (variant 1) keeps its own certification.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .module_helpers import typed_damage
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value

PACKET_SHA256 = "004116a55524cf55d387d236bcd22e8fbad9b79deb5679fc0c2be4257d364c0a"

# The burrow heal's level row, which the cache labels as damage.
_P_LEVEL_ROW = "Max Health Damage"


def _fury_of_the_xersai(compiled):
    """P: carry the burrow's Fury-scaled heal when the user declares Fury."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = compiled(ctx)
        if entry is None:
            return None
        fury = max(0, min(100, int(ctx.option("p_burrow_fury"))))
        if fury <= 0:
            return entry
        percent = extract_value(
            ctx.ability("P") or {}, _P_LEVEL_ROW, ctx.level, level=ctx.level
        )
        amount = fury / 100.0 * percent / 100.0 * float(ctx.stat("health"))
        if amount <= 0.0:
            return entry
        entry["self_heal_state"] = {"fury": fury, "amount": amount}
        entry["detail"] = (
            f"Burrow consumes {fury} Fury: {fury}% of {percent:g}% maximum "
            f"health ({amount:.1f})"
        )
        return entry

    return parse


def _queens_wrath(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q variant 0: all three empowered attacks, declared at the cast."""
    return typed_damage(ctx, "Total Bonus Physical Damage", "physical", time_offset=0.0)


def _furious_bite(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: physical bite, or the 120% true-damage variant at max Fury."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    fury = max(0, min(100, int(ctx.option("e_fury"))))
    if fury >= 100:
        value = extract_named(ability, "True Damage", rank, ctx.stats, ctx.target)
        dtype = "true"
        detail = (
            "Maximum Fury: Furious Bite deals 120% damage converted to "
            "true damage (the cached True Damage row: 84-204 + 72% bonus "
            "AD)"
        )
    else:
        value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
        dtype = "physical"
        detail = (
            f"Fury {fury}/100: the physical bite (70-170 + 60% bonus AD); "
            "at 100 Fury the E packet prices the true-damage variant"
        )
    entry = damage_entry(
        ability.get("name", "Furious Bite"),
        rank,
        extract_cooldown(ability, rank),
        value,
        dtype,
        # One bite on the target, at the cast boundary — the claim that
        # carries MODULE_CC's reviewed answer for E into the event ledger.
        event_order_certified="single_hit",
    )
    entry["parts"] = (DamagePart(dtype, value),)
    entry["detail"] = detail
    return entry


# Cached kit review.  Both Q variants only damage — Queen's Wrath's
# empowered attack "deal[s] bonus physical damage to the target and
# surrounding enemies" and Prey Seeker's bolt deals "magic damage to all
# nearby enemies and reveal[s] them".  W's Unburrow "deal[s] magic damage
# to nearby enemies and knock[s] them up for 1 second" (minions and small
# monsters get the knock back instead, and never reach a champion fight).
# E "bites the target enemy, dealing physical damage" and applies nothing;
# its "immobilized" wording is about Rek'Sai being unable to enter a
# tunnel.  R "slashes at the target with her claws, dealing physical
# damage".  P is Fury generation and healing, with no damage row.
MODULE_CC = {"Q": "none", "W": "knockup", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rek'Sai",
    PACKET_SHA256,
    # Prey Seeker's bolt and Unburrow's emergence each land one hit, like
    # Void Rush already did — the boundary claim that carries MODULE_CC's
    # reviewed answers into the event ledger.  Queen's Wrath prices three
    # empowered attacks and declares their aggregate at the cast instead.
    single_hit_slots=frozenset({"Q", "W", "R"}),
    variant_parsers={("Q", 0): _queens_wrath},
    slot_parsers={
        "E": _furious_bite,
    },
    slot_wrappers={"P": _fury_of_the_xersai},
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "e_fury",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 100,
        "step": 25,
        "label": (
            "Fury (0-100): at 100, Furious Bite deals 120% damage as true "
            "damage (the cached True Damage row)"
        ),
    },
    {
        "key": "p_burrow_fury",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 100,
        "step": 25,
        "label": "Fury consumed by the burrow that opens the fight (P heal)",
        "rotation": {
            "role": "self_state",
            "slot": "P",
            "note": (
                "The burrow heal is Fury Rek'Sai carried in, spent before "
                "the rotation starts; no cast orders it."
            ),
        },
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "E (Furious Bite) is deterministic through the e_fury option: below "
    "100 Fury it prices the physical row (70-170 + 60% bonus AD); at 100 "
    "Fury it prices the sourced true-damage variant (84-204 + 72% bonus "
    "AD == 120% of the physical row, 'converted to true damage').  Fury "
    "generation and decay are not simulated, and Burrow's CC remains "
    "documented out-of-scope",
    "Q variant 0 (Queen's Wrath) prices all three empowered attacks — "
    "the cached Total Bonus Physical Damage row (90/105/120/135/150% "
    "AD), three times the per-attack Bonus Physical Damage row the "
    "generated packet selected.  The aggregate is declared at the cast "
    "boundary; the attacks' spacing across the 3-second window and the "
    "primary target's critical-strike modifiers are not priced.",
    "P (Fury of the Xer'Sai) heals 0% : 100% (based on Fury) of "
    "9% : 21.29% (based on level) maximum health when Rek'Sai burrows — "
    "the cached P level row, which the wiki data mislabels 'Max Health "
    "Damage'. p_burrow_fury (default 0) is the Fury the burrow that "
    "opens the fight consumes and the heal lands at the fight's first W "
    "cast; it is a separate input from e_fury, which is the Fury she has "
    "re-earned by the time Furious Bite is cast. The 3-second consume is "
    "paid as one receipt, and its stop-at-full-health clause is the "
    "survival walk's overheal rather than a cap applied here.",
]

# No MODULE_COVERAGE: P now prices the burrow heal the self-heal rule
# places, so every slot in SLOTS prices a row the engine consumes, which
# is what the contract derives.

SELF_HEALING_RULE = declare_healing_rule("Rek'Sai")

"""Tahm Kench: acquired-taste and defensive-state packets.

E (Thick Skin) stays off the slot map, because it damages nothing and a slot
would invent a cast, so ``MODULE_COVERAGE`` states it ``no_damage`` rather than
deriving the ``out_of_scope`` of an unmodelled gap.  All three cached E effects
affect Self, and the parser's "Max Health Damage" attribute on the second is its
generic name for a percent-of-maximum-health self restore, not damage dealt, the
same misparse as Rek'Sai P.
The mechanic is priced elsewhere: the shared grey-health primitive, reached
through ``healing.GREY_HEALTH_RULE_CHAMPIONS``, reads E's rank off the skill
order and works the incoming ledger.  A level-18 probe at E rank 5 against 314.4
post-mitigation stored 147.75 and healed the same four seconds after the last
hit, which lands only when the fight leaves him those four seconds.
The E ACTIVE, grey health converted into a 2.5-second shield, rides the same
primitive: the pool is walk state, so a parse-time ``attach_self_shield``
payload cannot read it, and the presses are authored beside the consume heal
from the incoming ledger under ``e_convert_grey_shield``.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option, int_option
from .module_helpers import innate_on_hit, ranked_slot
from .shared_option_keys import TAHM_KENCH_GREY_SHIELD
from .slot_cc import CC_PER_PART
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

_acquired_taste = innate_on_hit(
    "Per-Level Scaling",
    "magic",
    name="An Acquired Taste",
    detail="basic attacks and Tongue Lash apply one stack",
)


@ranked_slot
def _tongue_lash(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    # Tongue Lash's row carries a per-rank base and an eighteen-entry per-level
    # term, so reading it needs the level as well as the rank.
    total = extract_named(
        ability, "Magic Damage", rank, ctx.stats, ctx.target, level=ctx.level
    )
    stacks = min(max(int(ctx.option("q_passive_stacks")), 0), 3)
    if stacks:
        total += extract_named(
            ctx.ability("P") or ability,
            "Per-Level Scaling",
            ctx.level,
            ctx.stats,
            ctx.target,
        )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    # Q's crowd control is stack-dependent, so it is authored on the part
    # rather than declared once in MODULE_CC: the lash "deals magic damage
    # to the first enemy hit and slows them by 50% for 2 seconds", and the
    # "An Acquired Taste Bonus" at three stacks adds "The target is
    # stunned for 1.5 seconds" on top of it.
    entry["parts"] = (
        DamagePart(
            "magic",
            total,
            time_offset=0.0,
            cc_kind="stun" if stacks >= 3 else "slow",
        ),
    )
    entry["detail"] = f"{stacks} Acquired Taste stack(s) before Q"
    return entry


def _regurgitate(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked("R", 1)
    if ranked is None:
        return None
    ability, rank = ranked
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ctx.ability("R") or ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.4),)
    entry["detail"] = "enemy Regurgitate target"
    return entry


SLOTS = {
    "P": _acquired_taste,
    "Q": _tongue_lash,
    # One emergence, one blow ("dealing magic damage to nearby enemies and
    # knocking them up and stunning them for 1 second").
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    # Thick Skin is grey-health/shield state, not damage; omitting it keeps
    # the damage timeline from inventing an enemy hit.  The E8a grey-health
    # primitive authors the E store (15/23/31/39/47% by rank, 42-50% with
    # 2+ visible enemies) and the out-of-combat restore heal from the
    # incoming ledger; the E active (grey -> 2.5 s shield) stays out of
    # the heal primitive's scope.
    "R": _regurgitate,
}

# Reviewed crowd control, read from the cached kit.  W (Abyssal Dive)
# lands "dealing magic damage to nearby enemies and knocking them up and
# stunning them for 1 second" — two immobilize kinds on one target, so the
# reviewed answer is the un-narrowed one.  R prices Regurgitate, the spit
# at the end of Devour, and Devour "can only be cast on enemies with 3
# stacks of An Acquired Taste", whose bonus reads "The target is
# suppressed during Devour's cast time and while attached".  P is an
# on-hit rider on the attack stream and Q's answer is stack-dependent, so
# Q authors its own kind on its part.
MODULE_CC = {"Q": CC_PER_PART, "W": "immobilize", "R": "suppression", "P": "none"}

parse_abilities = build_parser(SLOTS, "Tahm Kench", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option(
        "q_passive_stacks",
        0,
        minimum=0,
        maximum=3,
        label="Acquired Taste stacks before Q",
        rotation={"role": "self_state", "slot": "Q"},
    ),
    bool_option(
        TAHM_KENCH_GREY_SHIELD,
        False,
        label="Thick Skin: press the active to convert grey health",
        # Defensive self-state: it converts a pool the incoming ledger
        # banked and never sets up or consumes an outgoing cast.
        rotation={"role": "self_state", "slot": "E"},
    ),
]

ASSUMPTIONS = [
    "An Acquired Taste is an explicit on-hit rider; Q may opt into the bonus damage "
    "from a pre-existing stack state.",
    "Thick Skin stores 15/23/31/39/47% of post-mitigation damage taken as grey "
    "health.",
    "With 2 or more visible enemies that is 42/44/46/48/50%.",
    "The out-of-combat consume after 4s restores 60 to 100% by level of the pool as a "
    "heal.",
    "The grey-health primitive authors it from the incoming ledger.",
    "E's active converts the banked grey into a 2.5s shield on its cached 3s "
    "haste-scaled cooldown.",
    "Pressing it is a player decision, so e_convert_grey_shield is off by default and "
    "presses earliest.",
    "A press blocks the out-of-combat heal until its cooldown runs out; the residual "
    "bank still pays it.",
    "R defaults to the enemy Regurgitate branch; ally Devour is a separate "
    "support/shield scenario.",
    "E (Thick Skin) has no enemy-damage formula: all three cached effects are "
    "self-directed.",
    "They are the store percentage, the out-of-combat consume-heal and the shield "
    "conversion.",
    "The 'Max Health Damage' attribute is the parser's generic name for the self "
    "heal-restore share.",
    "It is not a term dealt to an enemy, the Rek'Sai P precedent.",
    "E is deliberately absent from SLOTS so the ledger never invents an enemy hit.",
    "MODULE_COVERAGE records a sourced no_damage rather than an unmodeled gap.",
]

SOURCES = load_champion_sources("Tahm Kench")


# E damages nothing, so it is a reviewed no-damage slot rather than the
# unmodeled gap the slot map would otherwise derive.
MODULE_COVERAGE = coverage(no_damage="E")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Tahm Kench self-healing events from its authored packet."""
    q_rank = _healing.parsed_rank(ctx.ability_damages, "Q")
    (q_flat,) = ctx.ranked_rows("Q", "Heal")
    q_missing_pct = _healing.leveling_modifier(
        _healing.ability_json(ctx.champion_data, "Q"), "Heal", q_rank, 1
    )
    return _healing.cast_heals(
        "Q",
        "Tongue Lash",
        ctx.damage_events,
        ctx.cast_timeline,
        amount_formula=_healing.flat_plus_missing_heal(q_flat, q_missing_pct),
    )


SELF_HEALING_RULE = self_healing_rule("Tahm Kench")(derive_self_healing)

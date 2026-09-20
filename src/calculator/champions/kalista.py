"""Kalista: stateful combat packets.

Soul-Marked damage needs an Oathsworn state and Rend is a stack count, not a
constant, so both stay explicit here; every number still comes from the pinned
champion cache.
P (Martial Poise) is ``no_damage``: all four cached effect rows carry empty
leveling, the windup dash, its boots-tier range table and the Oathsworn Bond
declaration being movement and state prose, and the binary's passive spells
carry no calculations at all, only dash duration, speed and range.
R (Fate's Call) is ``no_damage``: its one leveling row is "Airborne Duration",
a control duration rather than a damage value, and the binary's only named
value is the matching ``KnockupDuration``.  R lands on the Oathsworn ally as
retrieval, cleanse and invulnerability, or on enemies as pure knockback, so
``MODULE_CC`` leaves R unreviewed rather than declaring a kind no event could
carry.
"""

import re
from collections.abc import Mapping
from typing import Any

from ..ability_prose import CachedSentence
from ..ability_spec import DamagePart
from .charge_cadence import ChargeRule
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import named_damage, no_damage_slot, ranked_slot
from .slot_control import with_control_event
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .source_receipts import load_champion_sources

_pierce = named_damage("Physical Damage", "physical", time_offset=0.0)


def _soul_marked(ctx: SlotCtx) -> dict[str, Any] | None:
    """W's damage only exists after both tethered marks are present."""
    if not bool(ctx.option("soul_mark_proc")):
        return None
    ranked = ctx.ranked("W")
    if ranked is None:
        return None
    ability, rank = ranked
    total = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        "Soul-Marked", rank, extract_cooldown(ability, rank), total, "magic"
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.0),)
    entry["detail"] = "Oathsworn and Kalista marks consumed"
    return entry


_REND_WINDOW = CachedSentence(
    re.compile(
        r"apply a stack of Rend to enemies for (?P<seconds>\d+(?:\.\d+)?) seconds"
        r"[^.]*?stacking up to (?P<stacks>\d+) times"
    ),
    missing=(
        "Kalista E: the cached entry no longer states Rend's stack life and "
        "cap ('apply a stack of Rend to enemies for N seconds ... stacking "
        "up to N times')"
    ),
)


def _rend_window(ability: Mapping[str, Any]) -> dict[str, Any]:
    """The cached life and cap of a Rend stack, and what lodges one."""
    seconds, stacks = _REND_WINDOW.stack_terms(ability)
    return {
        "arming_slots": (),
        "max_stacks": stacks,
        "hits_required": stacks,
        "stacks_from_swings": True,
        "stacks_from_ability_hits": True,
        "stack_seconds": seconds,
        "armed_at_start": False,
        "requested": False,
    }


@ranked_slot
def _rend(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    requested = ctx.options.get("rend_stacks")
    window = _rend_window(ability)
    stacks = (
        min(max(int(requested), 1), window["max_stacks"])
        if requested is not None
        else 1
    )
    first = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    additional = extract_named(
        ability, "Bonus Damage per Additional Stack", rank, ctx.stats, ctx.target
    )
    total = first + max(0, stacks - 1) * additional
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    if requested is None:
        # Her basic attacks and Pierce lodge the spears Rend rips out, so
        # the level it consumes is a count of the hits that landed before
        # the cast (champions/armed_procs.py). The floor of one is the
        # module's own reviewed rail and it stands: ripping out spears
        # implies a spear, so a cast with none counted still prices one.
        entry["parts"] = (
            DamagePart(
                "physical",
                total,
                time_offset=0.0,
                stack_scaled_damage=(
                    lambda level: first + max(0, max(level, 1) - 1) * additional
                ),
            ),
        )
        entry["stack_window"] = window
        entry["detail"] = (
            f"Rend consumes the spears her hits lodged: {first:.2f} for the "
            f"first and {additional:.2f} for each additional, over the "
            f"{window['stack_seconds']:g}s a stack holds"
        )
    else:
        entry["parts"] = (DamagePart("physical", total, time_offset=0.0),)
        entry["detail"] = f"{stacks} Rend stack(s)"
    return entry


# P: the windup-dash mechanic — documented zero-damage row.
#
# All four cached effect rows carry empty leveling; Martial Poise is
# pure movement/state (the dash itself and the Oathsworn Bond
# declaration), with no damage attribute of its own.
_martial_poise = no_damage_slot(
    "Martial Poise is the windup-dash mechanic and the Oathsworn "
    "Bond declaration; all four cached effect rows carry empty "
    "leveling (data/champions.json Kalista P) and the game "
    "binary's dash spells (KalistaPassiveDashSpell(Actual)) carry "
    "no mSpellCalculations table — only dash duration/speed/range "
    "parameters. P prices nothing."
)


# R: the ally-retrieval/CC ultimate — documented zero-damage row.
#
# R's only sourced number is Airborne Duration (a CC duration, not
# damage); every other effect is a state applied to the Oathsworn ally
# (retrieval, cleanse, invulnerability) or a knockback on enemies.
_fates_call = no_damage_slot(
    "Fate's Call retrieves and holds the Oathsworn ally (cleanse, "
    "invulnerability, untargetable), lets them dash with "
    "displacement immunity, then knocks back and keeps nearby "
    "enemies airborne on landing — no damage sentence anywhere in "
    "the cached entry (data/champions.json Kalista R); its only "
    "leveling row is 'Airborne Duration' (1/1.5/2s), a CC "
    "duration. Corroborated by the game binary (KalistaRx and its "
    "child spells): the only named DataValues entry is "
    "KnockupDuration [0, 1, 1.5, 2, ...], matching the wiki "
    "value, and no spell record carries a mSpellCalculations "
    "table. R prices nothing; its effects land on the Oathsworn "
    "ally or as pure enemy CC."
)


SLOTS = {
    "P": _martial_poise,
    "Q": _pierce,
    "W": _soul_marked,
    "E": _rend,
    # Fate's Call prices no damage; its airborne is the cached
    # "Airborne Duration" row (1/1.5/2s) on the enemy-side effect.
    "R": with_control_event(
        _fates_call,
        duration_attr="Airborne Duration",
    ),
}

# Pierce's spear and the Soul-Mark consumption only damage; Rend rips the
# spears out "to deal physical damage and slow them for 2 seconds".  R
# prices no damage part, so its airborne rides the entry as a sourced
# ControlEvent instead.  P stays absent — unreviewed rather than
# reviewed-no-CC.
MODULE_CC = {"Q": "none", "W": "none", "E": "slow", "R": "airborne", "P": "none"}


# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "W": ChargeRule(
        why=(
            "W (Sentinel) banks sentinels on its cached rechargeRate "
            "(50s at rank 5), not on the 30s gap between two banked "
            "casts. The cached stock of 2 is not spent here: a sentinel "
            "stays posted."
        ),
        charges=1,
    )
}
parse_abilities = build_parser(
    SLOTS, "Kalista", cc_kinds=MODULE_CC, charge_rules=CHARGE_RULES
)

OPTIONS = [
    int_option(
        "rend_stacks",
        1,
        minimum=1,
        maximum=254,
        label=(
            "Rend stacks; unset derives them from the hits that lodged a "
            "spear before the cast, with the module's floor of one"
        ),
        derives=True,
        rotation={
            "role": "consume",
            "slot": "E",
            "condition": "rend",
            "kind": "stack_consume",
        },
    ),
    bool_option(
        "soul_mark_proc",
        False,
        label="Soul-Marked proc is armed",
        rotation={
            "role": "consume",
            "slot": "W",
            "condition": "soul-mark",
            "kind": "mark_consume",
            "setup_slot": "auto_stream",
            "note": (
                "W's damage consumes the Oathsworn/Kalista marks applied "
                "by the auto stream — no cast-slot applier, so no "
                "cross-slot edge; the option gates W's presence in the "
                "rotation."
            ),
        },
    ),
]

ASSUMPTIONS = [
    "W damage is withheld unless the Oathsworn and Kalista marks are explicitly armed.",
    "Rend defaults to one lodged spear; the stack count is explicit and capped at the "
    "sourced 254-stack limit.",
    "Fate's Call and Martial Poise are utility/state effects with no direct enemy damage.",
    "P (Martial Poise) and R (Fate's Call) carry no sourced damage/heal/shield "
    "row of their own (P's four effect rows are all empty leveling; R's only "
    "leveling row is a CC duration, Airborne Duration) — both are no_damage, "
    "not out_of_scope, and each emits an explicit zero-damage state row "
    "rather than staying silently absent.",
]

SOURCES = load_champion_sources("Kalista")

# P and R emit a row but price no damage, which is not what SLOTS derives.
MODULE_COVERAGE = coverage(no_damage="PR")

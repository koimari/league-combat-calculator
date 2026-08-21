"""Zaahen — CP10.10 full-entry-reviewed packet module.

Wiki-sourced item on-hit application is attached as a post-process on the
batch parser output (the batch parser builds its slot map at build time, so
declarations cannot be injected into the slot dict after the fact).

Roadmap session 5 slot 14 (2026-08-21): P (Cultivation of War) has no
enemy-damage formula: both cached effects are self-only — stacking bonus
attack damage (1.5% : 2.95% AD per stack, doubled at maximum stacks) and
a lethal-damage resurrection with a self-heal, with no term dealt to an
enemy (confirmed by the pinned reviewed packet's kind="no_damage"
declaration for P, and live: parse_champion_abilities emits P as a zero
total_raw row absent from the fight breakdown). P is not one of the
slots this module reassigns (only Q is overridden above), so it falls
to build_packet_module's default no-damage branch. MODULE_COVERAGE was
simply stale, still reading "out_of_scope" for an already-covered slot
(the Rek'Sai/Renekton precedent). Reclassified to "no_damage"; zero
fight-computation change.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "5f5796aa0364becd253cbb3b7b05939147841a3f76e41cfa061242d344ec9f63"


def _darkin_glaive(ctx: SlotCtx) -> dict[str, Any] | None:
    """Price the selected Q row from Zaahen's three sourced Q variants."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    try:
        variant = int(ctx.options.get("q_variant", 0))
    except (TypeError, ValueError):
        variant = 0
    variant = max(0, min(variant, 2))
    attributes = (
        "Total Physical Damage",
        "Physical Damage per Hit",
        "Bonus Physical Damage",
    )
    attribute = attributes[variant]
    sourced_amount = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    count = 2 if variant < 2 else 1
    amount = sourced_amount / 2.0 if variant == 0 else sourced_amount
    entry = damage_entry(
        ability.get("name", "The Darkin Glaive"),
        rank,
        extract_cooldown(ability, rank),
        sourced_amount if variant != 1 else sourced_amount * count,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical", amount=amount, count=count, time_offset=0.0, hit_interval=0.0
        ),
    )
    entry["detail"] = f"Q variant: {attribute}."
    return entry


_darkin_glaive.phase = "damage"

_base_parse, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zaahen",
    PACKET_SHA256,
    assumption_overrides=(
        "The Darkin Glaive prices both strikes (Physical Damage per Hit x 2 "
        "== Total Physical Damage).",
        "P (Cultivation of War) has no enemy-damage formula: both cached "
        "effects are self-only (stacking bonus AD, and a lethal-damage "
        "resurrection with a self-heal) — confirmed by the pinned "
        "reviewed packet's kind='no_damage' declaration for P. P is a "
        "cast slot in this module (never reassigned away from "
        "build_packet_module's no_damage branch), so MODULE_COVERAGE "
        "reflects a sourced no-damage classification rather than an "
        "unmodeled gap (no_damage, not out_of_scope).",
    ),
    slot_parsers={
        "Q": _darkin_glaive,
    },
)
PACKET_SPEC = SLOTS.packet_spec

OPTIONS = list(OPTIONS) + [
    {
        "key": "q_variant",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "Q damage variant",
    }
]

_ON_HIT_SPECS: dict[str, dict] = {
    "Q": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

_parse_abilities = _base_parse


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Zaahen self-healing events from its authored packet."""
    healing = []
    q_rank = _healing._rank(ability_damages, "Q")
    q_heal_pct = _healing._leveling_value(
        _healing._ability(champion_data, "Q"), "Champion Healing", q_rank
    )
    q_heal = q_heal_pct / 100.0 * float(champion_stats.get("health", 0.0))
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "Q"
    ):
        _healing._heal_from_damage(
            healing, event, q_heal, "The Darkin Glaive", link_to_damage=False
        )
    # Grim Deliverance (R): flat heal per champion hit
    # ("Healing per Champion hit": 82.5 / 132 / 181.5 (+ 66% bonus
    # AD)); the 1v1 pair fight sees exactly one hit per R cast.
    r_rank = _healing._rank(ability_damages, "R")
    r_heal = _healing.extract_named(
        _healing._ability(champion_data, "R"),
        "Healing per Champion hit",
        r_rank,
        champion_stats,
        {},
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        _healing._heal_from_damage(
            healing, event, r_heal, "Grim Deliverance", link_to_damage=False
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Zaahen", derive_self_healing)

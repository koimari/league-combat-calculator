"""Sivir — CP10.7 full-entry-reviewed packet module, plus the E9-3 Q fix.

E9-3: Boomerang Blade (Q) is a two-way blade: "Upon reaching maximum
range, the crossblade returns to her ... dealing the same damage to
enemies on its way back" — the cached "Total Maximum Champion Damage"
row (120-320 + 140% bonus AD + 120% AP) is exactly double the
single-pass "Physical Damage" row the reviewed packet priced.  The
module now prices the Total row so a full out-and-back pass deals the
in-game 2x damage (320 at rank 5 vs the old 160).
"""

from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    required_ability_atom,
    required_ranked_attribute_atom,
    ranked_ability_atom_value,
)
from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "ac50a4316c8ffc3f6f326c6be14ec20867f6301066621ff49ec26c1fad1b97a7"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sivir", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec


def _boomerang_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the two-way pass priced from the Total Maximum Champion Damage row."""
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    total = extract_named(
        ability, "Total Maximum Champion Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Boomerang Blade"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total / 2.0, count=2),)
    entry["detail"] = (
        "two-way Boomerang Blade: the crossblade hits out AND back for 2x "
        "(Total Maximum Champion Damage 120-320 + 140% bonus AD + 120% AP "
        "== 2 x the single-pass row)"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["Q"] = _boomerang_blade

# Sourced from the cached Spell Shield description.  The duration is read
# through the typed ability-atom accessor (``timing.active_duration``, the
# description's "for 1.5 seconds" prose atom); the 0.25s heal delay has NO
# atom in the catalog (prose-only — recorded SOURCE GAP in the slice
# handover), so it stays a module-authored sourced literal.
_SPELL_SHIELD_HEAL_DELAY_SECONDS = 0.25

_ATOM_RECEIPT_KEYS = (
    "atom_id",
    "behavior",
    "source",
    "values",
    "units",
    "evidence",
    "hash",
)


def _atom_receipt(atom: dict[str, Any]) -> dict[str, Any]:
    """One JSON-safe atom receipt (the interaction-atoms shape)."""
    return {key: atom[key] for key in _ATOM_RECEIPT_KEYS}


def _spell_shield(ctx: Any) -> dict[str, Any] | None:
    """E: one timed spell shield with its sourced block heal.

    Numeric values ride the typed ability-atom accessors: the 1.5s window
    (``timing.active_duration``) and the Heal row (60-80% AD + 50% AP by
    rank).  The 0.25s heal delay is prose-sourced (no atom exists).
    """
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    duration_atom = required_ability_atom(
        "Sivir",
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source="Sivir.E[0].effects[0].description",
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if duration_atom.get("units") != ["s"]:
        raise ValueError("Sivir E spell-shield duration atom must use seconds")
    duration = ranked_ability_atom_value(
        duration_atom, 1, source="Sivir.E[0].effects[0].description"
    )
    ad_ratio, ad_atom = required_ranked_attribute_atom(
        "Sivir", champion_data, "E", "Heal", rank, modifier_index=0
    )
    ap_ratio, ap_atom = required_ranked_attribute_atom(
        "Sivir", champion_data, "E", "Heal", rank, modifier_index=1
    )
    heal = (
        ad_ratio * float(ctx.stats.get("attack_damage", 0.0)) / 100.0
        + ap_ratio * float(ctx.stats.get("ability_power", 0.0)) / 100.0
    )
    return {
        "name": ability.get("name", "Spell Shield"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "total_raw": 0.0,
        "damage_type": "magic",
        "parts": (),
        "self_state_events": [
            {
                "kind": "spell_shield",
                "duration": duration,
                "source": ability.get("name", "Spell Shield"),
                "on_block_heal_amount": heal,
                "on_block_heal_delay": _SPELL_SHIELD_HEAL_DELAY_SECONDS,
                "on_block_heal_source": "Spell Shield · Heal",
                "source_atoms": [
                    _atom_receipt(duration_atom),
                    _atom_receipt(ad_atom),
                    _atom_receipt(ap_atom),
                ],
            }
        ],
        "detail": (
            "Spell Shield blocks one hostile effect during the sourced "
            f"{duration:g}s window and heals Sivir for {heal:g} after the "
            "sourced 0.25s delay."
        ),
    }


SLOTS["E"] = _spell_shield
parse_abilities = build_parser(SLOTS, "Sivir")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Boomerang Blade) prices the full two-way pass from the cached "
    "'Total Maximum Champion Damage' row (120-320 + 140% bonus AD + "
    "120% AP == 2 x the single-pass 'Physical Damage' row): the blade "
    "deals the same damage on the way out and back.",
    "The exact return cadence is not cached; both passes are priced at "
    "the cast boundary.",
    "E (Spell Shield) grants a 1.5 second shield (atom-backed: "
    "timing.active_duration 4d718bc78f540f0a). The first hostile ability "
    "effect during that window is blocked. The cached Heal row is applied "
    "after the sourced 0.25 second delay (prose-only — no catalog atom "
    "exists; recorded SOURCE GAP). Fleet of Foot is state and stays "
    "outside the damage ledger.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

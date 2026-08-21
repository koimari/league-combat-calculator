"""Swain — CP10.8 full-entry-reviewed packet module.

Roadmap session 4 batch G (2026-08-21): P (Ravenous Flock) is a Soul
Fragment collection mechanic, not enemy damage: its one cached effect
(data/champions.json P) reads as permanent bonus health per stack (15
bonus health) plus a self-heal on claim (6% of maximum health) — an empty
leveling row, ``damageType: null``. The pinned reviewed packet
(static/reviewed-packets.json) independently declares P ``kind:
"no_damage"`` with a sourced reason, and P is not a slot this module
reassigns away from ``build_packet_module``'s cast slots, so it already
emits the packet's sourced zero-damage row today — MODULE_COVERAGE was
simply stale, still reading "out_of_scope" for an already-covered slot
(the Malzahar/Nasus precedent, roadmap session 4 batch D). Reclassified
to "no_damage"; zero fight-computation change.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "65d9e8cd0840ba7f346dd7faad26a485494c4825f438be91e63491b17ecc5169"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Swain", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
VARIANT_OPTION_KEYS = ("r_variant",)
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Ravenous Flock) has no enemy-damage formula: its one cached "
    "effect (Soul Fragment collection, +15 permanent bonus health per "
    "stack, 6% max-health self-heal on claim) carries an empty leveling "
    "row and damageType null (confirmed by the pinned reviewed packet's "
    "kind='no_damage' declaration for P). P is a cast slot in this "
    "module (never reassigned away from build_packet_module's no_damage "
    "branch), so MODULE_COVERAGE reflects a sourced no-damage "
    "classification rather than an unmodeled gap (no_damage, not "
    "out_of_scope).",
]
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
    """Resolve Swain self-healing events from its authored packet."""
    healing = []
    r_ability = _healing._ability(champion_data, "R")
    r_rank = _healing._rank(ability_damages, "R")
    heal_leveling = _healing.find_named_leveling(r_ability, "Heal per Tick")

    def swain_bonus_health(unit: str, value: float) -> float | None:
        if unit == "% of his bonus health":
            return value / 100.0 * float(champion_stats.get("bonus_health", 0.0))
        return None

    heal_per_tick = (
        _healing.sum_modifiers(
            heal_leveling,
            r_rank,
            champion_stats,
            {},
            modifier_override=swain_bonus_health,
        )
        if heal_leveling is not None
        else 0.0
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        _healing._heal_from_damage(
            healing,
            event,
            heal_per_tick,
            "Demonic Ascension",
            link_to_damage=False,
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Swain", derive_self_healing)

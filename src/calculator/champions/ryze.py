"""Ryze — CP10.7 full-entry-reviewed packet module.

Roadmap session 4 batch G (2026-08-21): P (Arcane Mastery — the passive is
unnamed on the wiki packet, "Innate") is a pure resource buff, not enemy
damage: its one cached effect reads "Ryze increases his maximum mana by
(10% per 100 AP)," with an empty leveling row — a self mana-scaling
mechanic. The pinned reviewed packet (static/reviewed-packets.json)
independently declares P ``kind: "no_damage"`` with a sourced reason, and P
is not a slot this module reassigns away from ``build_packet_module``'s
cast slots, so it already emits the packet's sourced zero-damage row today
— MODULE_COVERAGE was simply stale, still reading "out_of_scope" for an
already-covered slot (the Malzahar/Nasus precedent, roadmap session 4
batch D). Reclassified to "no_damage"; zero fight-computation change.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "9da3638ceb40ffff52f60102f737c9576d5d5c13e67a3149499cf273105ff4f2"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Ryze", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Arcane Mastery) has no enemy-damage formula: its one cached effect "
    "('increases his maximum mana by 10% per 100 AP') carries an empty "
    "leveling row (confirmed by the pinned reviewed packet's "
    "kind='no_damage' declaration for P). P is a cast slot in this module "
    "(never reassigned away from build_packet_module's no_damage branch), "
    "so MODULE_COVERAGE reflects a sourced no-damage classification "
    "rather than an unmodeled gap (no_damage, not out_of_scope).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

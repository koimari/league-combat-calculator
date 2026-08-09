"""Yuumi — CP10.10 full-entry-reviewed packet module.

E8d ally-support: E (Zoomies) grants the caster a shield (Shield 65-165 +
40% AP; scope self per the cached "grants herself a shield" prose).  R
(Final Chapter) heals allies hit by the waves (Heal per Hit x5 == Total
Heal, scope one_teammate).  Both events are authored by the engine's
ally-support scanner from cached leveling at the cast times; the module
declares E/R in SLOTS so the fight rotation casts them.  The attached-bonus
anchor transfer of E ("Affects the Anchor instead of Yuumi") is a scope
detection the scanner does not express — see E8d reply for the missing hook.
"""

from .packet_module import build_packet_module, full_plus_reduced_parser

PACKET_SHA256 = "1795828f6486a1da27c639b301d6ebca7047735f17a173075d41d59369c82942"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yuumi",
    PACKET_SHA256,
    assumption_overrides=(
        "Final Chapter prices all 5 waves (Magic Damage per Hit + 4 x "
        "Reduced Damage per Hit == Total Magic Damage).",
    ),
    slot_parsers={
        "R": full_plus_reduced_parser(
            full_attr="Magic Damage per Hit",
            reduced_attr="Reduced Damage per Hit",
            dmg_type="magic",
            reduced_count=4,
            time_offset=0.7,
            hit_interval=0.7,
            dot_duration=3.5,
        )
    },
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R"} else "out_of_scope") for slot in "PQWER"
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
    """Resolve Yuumi self-healing events from its authored packet."""
    healing = []
    r_rank = _healing._rank(ability_damages, "R")
    per_wave = _healing.extract_named(
        _healing._ability(champion_data, "R"), "Heal per Hit", r_rank, champion_stats
    )
    if per_wave > 0.0:
        for cast in cast_timeline or []:
            if cast.get("slot") != "R":
                continue
            start = float(cast.get("time", 0.0))
            for index in range(5):
                healing.append(
                    {
                        "time": start + index * 0.7,
                        "amount": float(per_wave),
                        "source": "Final Chapter",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Yuumi", derive_self_healing)

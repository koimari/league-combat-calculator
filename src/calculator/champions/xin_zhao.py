"""Xin Zhao — CP10.10 full-entry-reviewed packet module.

Roadmap session 5 slot 14 (2026-08-21): P (Determination) was audited for
the same stale-label MODULE_COVERAGE fix applied to the other nine
champions in this batch, and it is a DIFFERENT case — a genuine,
unresolved gap, not a stale label. Its cached prose (data/champions.json
P, effect index 1) states the third stack "consumes them all to deal
15% / 30% / 45% / 60% (based on level) AD (+ 5% / 10% / 15% / 20% (based
on level) AP) bonus physical damage" to the struck enemy AND heals Xin
Zhao — a real enemy-damage proc, not a self-only buff. Both P effects'
``leveling`` arrays are empty (the wiki parser never captured these
percentages as structured rows; they exist only as prose), so the
pinned reviewed packet's generic ``kind: "no_damage"`` / "contains no
enemy-damage formula" declaration is the packet-generation pipeline's
catch-all for "no structured leveling row found," not a reviewed claim
that the ability deals no damage — unlike Xerath's Mana Surge, Zaahen's
Cultivation of War, or the other seven no_damage reclassifications in
this batch, all confirmed self-only/state mechanics with no enemy-damage
prose at all. Relabeling P "no_damage" here would misrepresent a real,
unsourced-formula gap as "confirmed non-damaging" (fail-closed
violation). P therefore STAYS "out_of_scope" (the Wukong W / Dr. Mundo P
/ Rengar R precedent: discovered-but-unresolved formula stays open,
receipted, not mislabeled) pending a hand-authored parser that reads the
prose-sourced per-level AD/AP percentages as HARDCODED, verified
constants.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "c39efd0eac006d4b59799a0b3c5de44ef6ec31f9f9a23bea7ab8a25d2f4ccf64"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xin Zhao", PACKET_SHA256, single_hit_slots=frozenset({"R"})
)
PACKET_SPEC = SLOTS.packet_spec
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Determination) is NOT modeled and MODULE_COVERAGE correctly "
    "reads out_of_scope (not no_damage): the third on-hit stack deals "
    "real bonus physical damage to the struck enemy (15/30/45/60% AD + "
    "5/10/15/20% AP, based on level) per the cached prose, but both P "
    "leveling rows are empty arrays — the percentages exist only as "
    "text, never captured as sourced structured data. The pinned "
    "reviewed packet's kind='no_damage' declaration for P is the "
    "generic 'no structured leveling row' catch-all, not a reviewed "
    "non-damage claim; genuine unresolved gap, receipted rather than "
    "silently relabeled.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
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
    """Resolve Xin Zhao self-healing events from its authored packet."""
    healing = []
    lifesteal = float(champion_stats.get("lifesteal_percent", 0.0) or 0.0)
    if lifesteal > 0.0:
        for event in _healing._attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            amount = (
                0.333 * max(0.0, float(event.get("damage", 0.0))) * lifesteal / 100.0
            )
            _healing._heal_from_damage(healing, event, amount, "Wind Becomes Lightning")
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Xin Zhao", derive_self_healing)

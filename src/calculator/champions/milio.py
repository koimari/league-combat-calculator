"""Milio — CP10.4 full-entry-reviewed packet module.

E2 DoT fix: W (Cozy Campfire) heals 25 sourced ticks (Heal per Tick x25 ==
Total Heal) via the heal rule in src/calculator/healing.py.

E8d ally-support: W (Cozy Campfire, Total Heal 70-150 + 15% AP, scope
one_teammate) and R (Breath of Life, Heal 150-350 + 50% AP, scope
self_and_all_teammates) heal allies.  The events are authored by the engine's
ally-support scanner from cached leveling at the cast times; the module
declares W/R in SLOTS so the fight rotation casts them.

Wave-2 ally support (HANDOVER 8.5): the ally half of W is the sourced
Total Heal delivered as one lump packet at the cast — the per-tick cadence
(25 x Heal per Tick over the 6s fuemigo duration, "heal every 0.264
seconds") is priced only for Milio's own self-heal stream by the E1 rule.
The scanner fails closed on "Heal per Tick" packets without an authored
cadence, so the lump Total Heal is the deterministic ally packet.

Roadmap session 1 (2026-08-20): W, E, and R are reclassified from
out_of_scope to modeled. Every one of the three already carried a real,
sourced, tested numeric effect before this session — the label was simply
stale relative to the engine's ally-support/self-heal side channels:
  - W (Cozy Campfire): self heal via ``derive_self_healing`` below (tick
    stream) AND ally heal via the support scanner's "Total Heal" lump
    packet (support_effects.py; pinned in tests/test_e8_support.py,
    tests/test_ally_support_wave2.py).
  - E (Warm Hugs): ally/self shield via the support scanner's "Shield
    Strength" packet (Shield Strength 45-165 + 45% AP; pinned in
    tests/test_support_effects.py and tests/test_milio_r_cleanse.py's
    "Warm Hugs · Shield Strength" check).
  - R (Breath of Life): self_and_all_teammates heal authored below via
    ``derive_self_healing`` (Milio is in support_effects.py's
    ``_MODULE_AUTHORED_HEAL_SLOTS`` so the scanner correctly defers).
P (Fired Up!) stays out_of_scope and is NOT closed this session: the
enchant it grants ("Milio's ability hits on himself and allied champions
grant an enchantment for 4 seconds, which causes the NEXT basic attack OR
ability hit against enemies to deal bonus magic damage") is a real,
sourced number (7/11/15% of the enchanted target's bonus AD + a 10-101
per-level burn), but correctly attributing it needs to know, at the
moment each of Milio's W/E/R casts lands on himself, which action (an
auto attack or one of his OWN next ability casts) consumes the window —
and whether overlapping windows from back-to-back W/E/R casts refresh a
single consumable proc or would double/triple-count under the engine's
existing ``empowers_next_auto`` mechanism (which multiplies flatly by
num_casts and has no concept of one proc window being refreshed rather
than stacked by a second trigger inside the same fight). That live
event-ordering/dedup decision belongs to the rotation/cast-scheduling
engine (damage.py), which is out of this session's ownership boundary;
attempting a static per-slot approximation here risked inventing an
overcounted number rather than sourcing a correct one.
"""

from .packet_module import _rank_gated_no_damage, build_packet_module

PACKET_SHA256 = "fce2851d13e50c61a320c2195e1618e540b56a81742d3e44cfaa4a0ffe2c163f"

# P2 Slice 7: Breath of Life is heal/cleanse-only (no outgoing damage)
# AND unlearnable-while-absent — an R rank 0 must not book a cast (the
# engine rotates every SLOT at every rank; the E8d heal rule gates on
# the rank too).
_RANK_GATED_R = _rank_gated_no_damage(
    "R",
    reason="The pinned Wiki packet contains no enemy-damage formula for "
    "this slot; it is modeled as a non-damaging/state-only ability.",
)

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Milio", PACKET_SHA256, slot_parsers={"R": _RANK_GATED_R}
)
ASSUMPTIONS = [
    *ASSUMPTIONS,
    "Cozy Campfire (W) heals each selected teammate the sourced Total "
    "Heal (70-150 + 15% AP) as one lump packet at the cast; the 25-tick "
    "cadence (Heal per Tick x25 over the 6s fuemigo, every 0.264s) is "
    "priced only for Milio's own self-heal stream in healing.py, and the "
    "ally branch fails closed on per-tick rows rather than inventing a "
    "tick schedule.",
    "Warm Hugs (E) shields the selected teammate for the sourced Shield "
    "Strength (45-165 + 45% AP) for 2.5s and Breath of Life (R) heals "
    "Milio and every selected teammate the sourced Heal (150-350 + 50% "
    "AP) via the E1-rule fan-out; the 65% tenacity and cleanse are "
    "utility state.",
]
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    "P": "out_of_scope",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
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
    """Resolve Milio self-healing events from its authored packet."""
    healing = []
    r_rank = _healing._rank(ability_damages, "R")
    heal = _healing.extract_named(
        _healing._ability(champion_data, "R"), "Heal", r_rank, champion_stats
    )
    if heal > 0.0:
        for cast_index, cast in enumerate(cast_timeline or []):
            if cast.get("slot") != "R":
                continue
            healing.append(
                {
                    "time": float(cast.get("time", 0.0)),
                    "amount": heal,
                    "source": "Breath of Life",
                    "kind": "champion_ability",
                    "actor_wide": True,
                    "target_scope": "self_and_all_teammates",
                    "_event_id": f"milio:r:{cast_index}",
                }
            )
    # Cozy Campfire (W): the fuemigo heals Milio himself — "Milio counts
    # as an allied champion for this ability" — every tick over its
    # 6-second duration (wiki: "Heal per Tick: 2.8 / 3.6 / 4.4 / 5.2 / 6
    # (+ 0.6% AP)"; "Total Heal: 70 / 90 / 110 / 130 / 150 (+ 15% AP)").
    # The tick count is sourced from the Total/PerTick ratio (25) and
    # spread across the 6s duration -> 0.24s intervals.  The 0.264s
    # cadence in the description does not reconcile to the sourced 25
    # ticks, so the ratio-derived count wins, exactly as Janna's Monsoon
    # is handled.  W deals no enemy damage, so the W cast timeline is
    # the sourced trigger.
    w_rank = _healing._rank(ability_damages, "W")
    w_ability = _healing._ability(champion_data, "W")
    w_per_tick = _healing.extract_named(
        w_ability, "Heal per Tick", w_rank, champion_stats
    )
    w_total = _healing.extract_named(w_ability, "Total Heal", w_rank, champion_stats)
    w_tick_count = (
        max(1, min(100, int(round(w_total / w_per_tick))))
        if w_per_tick > 0.0 and w_total > 0.0
        else 25
    )
    if w_per_tick > 0.0:
        for cast in cast_timeline or []:
            if cast.get("slot") != "W":
                continue
            start = float(cast.get("time", 0.0))
            for index in range(1, w_tick_count + 1):
                healing.append(
                    {
                        "time": start + index * 0.24,
                        "amount": float(w_per_tick),
                        "source": "Cozy Campfire",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Milio", derive_self_healing)

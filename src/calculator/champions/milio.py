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
Roadmap session 2 (2026-08-20): P (Fired Up!) stays out_of_scope, but
the reason has CHANGED and the old one must not be reused.

Session 1 blocked P on a named ENGINE dependency: ``empowers_next_auto``
multiplies flatly by cast count and has no concept of a proc window
being refreshed rather than stacked, so back-to-back W/E/R casts would
have double/triple-counted a buff the cached notes say is only
refreshed.  **That dependency is now satisfied** — session 2 built
``damage.py``'s ``_empower_window_procs``, which walks the accepted cast
timeline against the fight's consuming actions and returns one timestamp
per charge actually spent (``consumed_by`` already accepts both ``auto``
and ``ability_hit``, which is exactly Fired Up!'s "next basic attack OR
ability hit").  Taric P rides it this session.  A future session must
therefore NOT re-open P expecting the dedup to be the blocker.

P is blocked instead on the SOURCE DATA, on three independent counts
(each verified against every cached artifact — the wiki entry's
description and ``leveling`` rows in data/champions.json, the game-file
atoms in data/atoms/v2/milio.atoms.v2.json, and data/gamefiles/ddragon/
Milio.json):

1. **The burst has no priceable magnitude.**  The burst is "7% / 11% /
   15% (based on level) of enchanted target's AD".  Those three values
   exist ONLY as prose: the cached P entry carries no ``leveling`` row
   for them, the atoms' ``ratios`` map is empty and their
   ``effect_amounts`` hold only the burn's BaseDamageStart/End (10/50),
   and ddragon's passive text is a numberless blurb.  Critically, no
   cached source states WHICH levels map to 7 / 11 / 15 — a three-value
   "(based on level)" bracket with no breakpoints cannot be evaluated at
   a level without inventing the schedule.  Contrast the burn, whose
   "(based on level)" DID parse into a per-level array, and Taric P,
   whose "25 : 101" parsed into a 20-entry ramp.
2. **The burst's scaling stat belongs to another champion.**  It reads
   the *enchanted target's* AD, and the cached notes tag it as proc
   damage "when the damage is triggered by allies".  The engine models a
   single attacker, so the ally-carried case — which is the entire point
   of an enchanter passive — has no attacker whose AD could source it.
3. **W's arming cadence is not the cast timeline.**  ``_empower_window_
   procs`` resolves ``armed_by`` slots to their CAST times.  W (Cozy
   Campfire) does not arm once at the cast: the hearth "applies Fired
   Up! every 3 seconds" over its 6s duration (ddragon tooltip's
   ``healfrequencyseconds``, atom ``HealFrequencySeconds`` = 3.0), and
   the W atom's ``reset_on`` reads "Fired Up! at most once every 3s".
   The primitive has no term for a repeating in-duration arm, so an
   ``armed_by=("W", ...)`` declaration would silently UNDERCOUNT W's
   arms.

So a "closed" P would have to invent the level breakpoints (1), stand in
someone else's AD (2), and mis-time W's arms (3).  All three fail closed
here rather than shipping a number; the blocker is pinned by
tests/test_milio_fired_up_blocker.py, which fails the moment any cached
source starts publishing the missing terms.
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
    "P (Fired Up!) is documented-only and stays out_of_scope: its burst "
    "(7% / 11% / 15% (based on level) of the enchanted target's AD) has "
    "no priceable magnitude in ANY cached source -- no leveling row in "
    "data/champions.json, an empty ratios map in the game-file atoms, a "
    "numberless ddragon blurb -- and no source states which levels map "
    "to 7 / 11 / 15, so the three-value bracket cannot be evaluated at a "
    "level without inventing the breakpoints. It fails closed instead.",
    "P (Fired Up!)'s burst scales with the ENCHANTED TARGET's AD and is "
    "tagged proc damage when an ally triggers it (cached P notes). This "
    "engine models a single attacker, so the ally-carried case has no "
    "attacker whose AD could source the term; only Milio's own "
    "self-enchant would ever be expressible, which is a fraction of the "
    "sourced effect and is withheld rather than reported as the whole.",
    "P (Fired Up!)'s window is NOT blocked on proc-window dedup any "
    "more -- damage.py's _empower_window_procs (built for Taric P) "
    "already expresses 'refresh, do not stack' and already accepts both "
    "auto and ability_hit consumers. It is blocked on W's arming "
    "CADENCE: the hearth applies Fired Up! every 3 seconds over its 6s "
    "duration (ddragon healfrequencyseconds, atom HealFrequencySeconds "
    "= 3.0), while the primitive resolves armed_by slots to cast times "
    "only, so declaring W as an arming slot would undercount its arms.",
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
